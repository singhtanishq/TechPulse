"""
TechPulse — Processor Utilities

Shared utilities for the collection, processing and generation layers.

Conventions:
    - All timestamps are timezone-aware UTC ISO-8601. TechPulse's
      reporting cycle, however, is anchored to India Standard Time
      (Asia/Kolkata, UTC+05:30 — no daylight saving).
    - The TechPulse reporting date is a DATE-ONLY value ("YYYY-MM-DD")
      representing one India calendar day. It is never parsed as a UTC
      instant; date-only values are compared as calendar dates.
    - The edition for reporting date X covers the previous IST calendar
      day (X-1): [X-1 00:00 IST, X 00:00 IST). The daily workflow fires
      at 18:30 UTC = 00:00 IST, i.e. at the start of edition day X.
    - "Latest raw file" selection is by dated filename (YYYY-MM-DD.json),
      not filesystem mtime, so file copies never change behavior.
    - Processed metadata timestamps are derived from source data so that
      reprocessing identical inputs yields byte-identical outputs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
NORMALIZED_DIR = DATA_DIR / "normalized"
GENERATED_DIR = PROJECT_ROOT / "generated"

# India Standard Time — fixed offset, no DST. (Asia/Kolkata has not
# observed DST since 1945, so a fixed offset is exact.)
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

# When the daily workflow fires on its 18:30 UTC (= 00:00 IST) slot,
# GitHub's scheduler may start the run slightly before or after the
# nominal time. A 90-minute forward buffer makes the intended reporting
# date robust to that jitter: a run starting just BEFORE midnight IST
# still resolves to the edition about to begin, and a run starting just
# after midnight resolves to the edition that just began.
SCHEDULE_JITTER_BUFFER_MINUTES = 90

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "NONE": 4,
}


# ------------------------------------------------------------------ #
# Clock + reporting date
# ------------------------------------------------------------------ #

def utc_now() -> datetime:
    """Return the current aware UTC time."""
    return datetime.now(timezone.utc)


def ist_now() -> datetime:
    """Return the current aware IST (Asia/Kolkata) time."""
    return utc_now().astimezone(IST)


def ist_today(offset_minutes: int = 0) -> str:
    """
    Return the current IST calendar date as YYYY-MM-DD, optionally
    shifted by whole minutes (positive = into the future).
    """
    instant = ist_now() + timedelta(minutes=offset_minutes)
    return instant.date().isoformat()


def ist_date_of(instant: datetime) -> str:
    """Return the IST calendar date (YYYY-MM-DD) of an aware instant."""
    return instant.astimezone(IST).date().isoformat()


def parse_ist_date(value: str) -> date:
    """Parse a strict YYYY-MM-DD reporting date. Raises ValueError."""
    parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    return parsed.date()


def ist_day_window(reporting_date: str) -> tuple[datetime, datetime]:
    """
    Return the UTC [start, end) instants covering the IST calendar day
    immediately preceding the reporting date.

    The edition for reporting date X observes the previous completed
    India day: [X-1 00:00 IST, X 00:00 IST). Both returned instants are
    timezone-aware UTC.
    """
    day = parse_ist_date(reporting_date)
    covered = day - timedelta(days=1)
    start_ist = datetime(covered.year, covered.month, covered.day, tzinfo=IST)
    end_ist = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def newest_snapshot_date() -> str | None:
    """
    Return the newest daily snapshot date (YYYY-MM-DD) by filename,
    or None when no dated snapshot exists yet.
    """
    if not DAILY_DIR.exists():
        return None
    dated = []
    for path in DAILY_DIR.glob("*.json"):
        try:
            parse_ist_date(path.stem)
        except ValueError:
            continue
        dated.append(path.stem)
    return max(dated) if dated else None


def resolve_reporting_date(
    event: str = "manual",
    input_date: str | None = None,
) -> tuple[str, str]:
    """
    Resolve the TechPulse reporting date for a pipeline run.

    Returns (date, explanation). Resolution order:

    1. Explicit input (workflow_dispatch input / CLI --date) — used
       verbatim after format validation.
    2. Otherwise, the earlier of:
         a. newest existing snapshot date + 1 day  (self-healing:
            backfills a day missed by a failed scheduled run and never
            skips ahead), and
         b. the IST calendar date of "now", shifted forward by the
            scheduler-jitter buffer for scheduled runs (a run that
            starts just before midnight IST belongs to the edition
            that is about to begin).

    Manual and push-triggered runs use "now" without the jitter buffer.
    """
    if input_date:
        try:
            parse_ist_date(input_date)
        except ValueError:
            raise ValueError(
                f"Reporting date must be YYYY-MM-DD (got '{input_date}')."
            )
        return input_date, f"explicit input date {input_date}"

    candidates: list[tuple[date, str]] = []

    newest = newest_snapshot_date()
    if newest:
        backfill = parse_ist_date(newest) + timedelta(days=1)
        candidates.append(
            (backfill, f"next pending edition after newest snapshot {newest}")
        )

    now_ist = ist_today(
        offset_minutes=SCHEDULE_JITTER_BUFFER_MINUTES
        if event == "schedule"
        else 0
    )
    candidates.append(
        (parse_ist_date(now_ist), f"current IST date ({event} run, IST={ist_now().isoformat()})")
    )

    chosen, reason = min(candidates, key=lambda item: item[0])
    return chosen.isoformat(), reason


# ------------------------------------------------------------------ #
# Window membership
# ------------------------------------------------------------------ #

def in_ist_day(value: str | None, ist_day: str) -> bool:
    """
    Whether a record timestamp falls on the given IST calendar day.

    Full ISO-8601 timestamps are converted to IST and compared by
    calendar date. Date-only values ("YYYY-MM-DD") are compared as
    calendar dates directly — never reinterpreted as UTC instants.
    Returns False for missing/unparseable values.
    """
    if not value or not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text == ist_day
    stamp = parse_iso_datetime(text)
    if stamp is None:
        return False
    return ist_date_of(stamp) == ist_day


# ------------------------------------------------------------------ #
# Parsing / persistence
# ------------------------------------------------------------------ #

def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string; returns None when unparseable."""
    if not value or not isinstance(value, str):
        return None
    try:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, returning None when missing or malformed."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_json(data: dict[str, Any], path: Path) -> Path:
    """Save JSON deterministically (sorted keys, stable newline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path


def latest_dated_file(directory: Path) -> Path | None:
    """
    Return the newest dated JSON file in a directory (by filename).

    Filenames must be YYYY-MM-DD.json so lexical order equals date order.
    Falls back to mtime ordering for non-conforming names.
    """
    if not directory.exists():
        return None
    files = [f for f in directory.glob("*.json") if f.is_file()]
    if not files:
        return None

    def sort_key(path: Path) -> tuple[int, str]:
        stem = path.stem
        try:
            parse_ist_date(stem)
            return (1, stem)  # dated files sort by name
        except ValueError:
            return (0, "")   # non-dated files sort first (ignored below)

    dated = [f for f in files if sort_key(f)[0] == 1]
    if dated:
        return max(dated, key=lambda f: f.stem)
    return max(files, key=lambda f: f.stat().st_mtime)


def derive_processed_at(source_files: list[Path | None]) -> str:
    """
    Derive a deterministic processedAt timestamp from source data.

    Uses the newest 'collectedAt' across the given source files so that
    reprocessing the same inputs never changes this value.
    Falls back to the current IST reporting-day start (as UTC) when
    sources are absent.
    """
    newest: datetime | None = None
    for path in source_files:
        if path is None:
            continue
        data = load_json(path)
        if not data:
            continue
        meta = data.get("meta") or {}
        stamp = parse_iso_datetime(meta.get("collectedAt"))
        if stamp and (newest is None or stamp > newest):
            newest = stamp
    if newest is not None:
        return newest.isoformat()
    window_start, _ = ist_day_window(ist_today())
    return window_start.isoformat()


# ------------------------------------------------------------------ #
# Formatting
# ------------------------------------------------------------------ #

def format_date(date_obj: datetime | str | None) -> str:
    """Format a date for display, e.g. '18 SEP 2026' (IST calendar day)."""
    if isinstance(date_obj, str):
        text = date_obj.strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return format_date(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=IST))
        parsed = parse_iso_datetime(text)
        if parsed is None:
            return ""
        date_obj = parsed
    if isinstance(date_obj, datetime):
        return date_obj.astimezone(IST).strftime("%d %b %Y").upper()
    return ""


def deduplicate_by_key(items: list[dict], key: str) -> list[dict]:
    """Deduplicate a list of dicts by a key, keeping the first occurrence."""
    seen: set[Any] = set()
    result: list[dict] = []
    for item in items:
        val = item.get(key)
        if val and val not in seen:
            seen.add(val)
            result.append(item)
    return result


def status_from_counts(total: int, in_window: int, failures: int = 0) -> str:
    """
    Derive an honest source status:
        empty   — source produced no data at all
        failed  — collection reported failures only
        partial — data collected but some items failed / nothing in window
        success — data collected and present in window
    """
    if total <= 0 and failures <= 0:
        return "empty"
    if total <= 0 and failures > 0:
        return "failed"
    if failures > 0 or in_window <= 0:
        return "partial"
    return "success"
