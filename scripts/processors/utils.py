"""
TechPulse — Processor Utilities

Shared utilities for the processing and generation layers.

Conventions:
    - All timestamps are timezone-aware UTC ISO-8601.
    - "Latest raw file" selection is by dated filename (YYYY-MM-DD.json),
      not filesystem mtime, so file copies never change behavior.
    - Processed metadata timestamps are derived from source data so that
      reprocessing identical inputs yields byte-identical outputs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
NORMALIZED_DIR = DATA_DIR / "normalized"
GENERATED_DIR = PROJECT_ROOT / "generated"

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "NONE": 4,
}


def utc_now() -> datetime:
    """Return the current aware UTC time."""
    return datetime.now(timezone.utc)


def previous_utc_day(reference: datetime | None = None) -> datetime:
    """Return midnight (UTC) of the previous completed UTC day."""
    if reference is None:
        reference = utc_now()
    day = (reference - timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


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
            datetime.strptime(stem, "%Y-%m-%d")
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
    Falls back to window end / previous day when sources are absent.
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
    return previous_utc_day().isoformat()


def format_date(date_obj: datetime | str | None) -> str:
    """Format a date for display, e.g. '18 SEP 2026'."""
    if isinstance(date_obj, str):
        parsed = parse_iso_datetime(date_obj)
        if parsed is None and date_obj:
            # Already a bare YYYY-MM-DD string.
            try:
                parsed = datetime.strptime(date_obj, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return ""
        date_obj = parsed
    if not isinstance(date_obj, datetime):
        return ""
    return date_obj.strftime("%d %b %Y").upper()


def format_relative_date(date_obj: datetime | str | None, now: datetime | None = None) -> str:
    """Format a relative date: Today / Yesterday / N days ago / absolute."""
    if isinstance(date_obj, str):
        parsed = parse_iso_datetime(date_obj)
        if parsed is None and date_obj:
            try:
                parsed = datetime.strptime(date_obj, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return ""
        date_obj = parsed
    if not isinstance(date_obj, datetime):
        return ""

    now = now or utc_now()
    delta = (now.date() - date_obj.date()).days

    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 14:
        return f"{delta} days ago"
    return format_date(date_obj)


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
