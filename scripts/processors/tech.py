#!/usr/bin/env python3

"""
TechPulse — Technology Processor

Normalizes RSS/Atom entries into the application-ready technology
dataset for one TechPulse reporting edition.

Reporting model:
    The edition for reporting date X covers the previous IST calendar
    day:

        [X-1 00:00 IST, X 00:00 IST)

RSS feeds are ephemeral. To reduce missed stories caused by feed
rotation, TechPulse intentionally applies a bounded 48-hour publication
lookback before the covered day's start.

An RSS entry is therefore eligible when:

    covered_day_start - 48h <= published_at < edition_day_start

The raw RSS file's meta.collectedAt records when the feed was observed.
The processor does not claim a stronger per-entry observation timestamp
than the source actually provides.

Source integrity:
    - The exact reporting-date raw file must exist.
    - The source file's meta.reportingDate must match the requested
      reporting date when that metadata exists.
    - Another reporting date's source file is NEVER substituted.
    - Missing, unreadable, malformed, or date-mismatched source data is
      reported as FAILED.
    - A healthy source with no eligible entries is reported as EMPTY.
    - Collector-reported failures produce PARTIAL when usable entries
      remain.

Output:
    data/normalized/tech.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    DATA_DIR,
    dated_file_for,
    derive_processed_at,
    ist_day_window,
    ist_date_of,
    ist_today,
    load_json,
    parse_ist_date,
    parse_iso_datetime,
    save_json,
)

TECH_DIR = DATA_DIR / "tech"
NORMALIZED_DIR = DATA_DIR / "normalized"

LOOKBACK_HOURS = 48


# ------------------------------------------------------------------ #
# Window resolution
# ------------------------------------------------------------------ #

def resolve_window(
    date_arg: str | None,
    start_arg: str | None,
    end_arg: str | None,
) -> tuple[datetime, datetime, str, str]:
    """
    Resolve:

        (window_start, window_end, covered_ist_day, reporting_date)

    Normal mode:
        --date X
        -> covered day is X-1
        -> reporting date is X

    Explicit-window mode:
        --start + --end
        -> use the supplied half-open window exactly
        -> covered day is the IST day containing window_start
        -> reporting date is either the supplied --date or the IST
           calendar date represented by window_end
    """

    if start_arg or end_arg:
        if not start_arg or not end_arg:
            raise ValueError(
                "--start and --end must be supplied together."
            )

        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)

        if start is None or end is None:
            raise ValueError(
                "Invalid --start/--end datetime."
            )

        if start >= end:
            raise ValueError(
                "--start must be earlier than --end."
            )

        covered_ist_day = ist_date_of(start)

        if date_arg:
            try:
                parse_ist_date(date_arg)
            except ValueError:
                raise ValueError(
                    f"Reporting date must be YYYY-MM-DD "
                    f"(got '{date_arg}')."
                )

            reporting_date = date_arg
        else:
            reporting_date = ist_date_of(end)

        return (
            start,
            end,
            covered_ist_day,
            reporting_date,
        )

    reporting_date = date_arg or ist_today()

    try:
        parse_ist_date(reporting_date)
    except ValueError:
        raise ValueError(
            f"Reporting date must be YYYY-MM-DD "
            f"(got '{reporting_date}')."
        )

    start, end = ist_day_window(reporting_date)

    return (
        start,
        end,
        ist_date_of(start),
        reporting_date,
    )


# ------------------------------------------------------------------ #
# Source loading + validation
# ------------------------------------------------------------------ #

def collector_failure_count(
    data: dict[str, Any],
) -> int:
    """
    Extract collector-reported failures from meta.failures.

    Current format:
        "failures": [...]

    A legacy integer form is handled defensively.
    """
    meta = data.get("meta") or {}
    failures = meta.get("failures", [])

    if isinstance(failures, list):
        return len(failures)

    if isinstance(failures, int):
        return max(failures, 0)

    return 0


def validate_source_reporting_date(
    data: dict[str, Any],
    expected_date: str,
    path: Path,
) -> bool:
    """
    Validate source reporting-date metadata.

    Older files without meta.reportingDate are accepted for backward
    compatibility. When the metadata exists, however, it must match
    exactly.
    """
    source_date = (
        (data.get("meta") or {})
        .get("reportingDate")
    )

    if source_date is None:
        return True

    if source_date != expected_date:
        print(
            f"  FAILED: source file {path.name} declares "
            f"reportingDate={source_date!r}, expected "
            f"{expected_date!r}"
        )
        return False

    return True


def load_rss_source(
    path: Path | None,
    reporting_date: str,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    int,
    str,
]:
    """
    Load the exact reporting-date RSS source.

    Returns:
        (source_data, entries, failures, status)

    Status:
        failed  -> missing/invalid/date-mismatched source
        partial -> usable entries plus failures
        empty   -> healthy source with zero entries
        success -> healthy source with usable entries
    """

    print("Loading tech/RSS data...")

    if path is None:
        print(
            f"  FAILED: exact RSS source file for "
            f"{reporting_date} is missing"
        )
        return None, [], 1, "failed"

    data = load_json(path)

    if data is None:
        print(
            f"  FAILED: RSS source is missing, unreadable, or "
            f"invalid JSON: {path.name}"
        )
        return None, [], 1, "failed"

    if not validate_source_reporting_date(
        data,
        reporting_date,
        path,
    ):
        return data, [], 1, "failed"

    entries = data.get("entries")

    if not isinstance(entries, list):
        print(
            f"  FAILED: {path.name} is missing the expected "
            "'entries' list"
        )
        return data, [], 1, "failed"

    valid_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
    ]

    malformed_count = (
        len(entries) - len(valid_entries)
    )

    failures = collector_failure_count(data)

    if malformed_count:
        failures += malformed_count
        print(
            f"  WARNING: ignored {malformed_count} malformed "
            f"RSS entry record(s)"
        )

    if failures > 0 and valid_entries:
        status = "partial"
    elif failures > 0:
        status = "failed"
    elif not valid_entries:
        status = "empty"
    else:
        status = "success"

    print(
        f"  Loaded {len(valid_entries)} entries from "
        f"{path.name} (status={status})"
    )

    if collector_failure_count(data):
        print(
            f"  Collector failures reported: "
            f"{collector_failure_count(data)}"
        )

    return (
        data,
        valid_entries,
        failures,
        status,
    )


# ------------------------------------------------------------------ #
# Entry validation
# ------------------------------------------------------------------ #

def valid_entry_identity(
    entry: dict[str, Any],
) -> bool:
    """
    Determine whether an entry has enough identity information to be
    meaningfully retained.

    A title or URL is sufficient for historical compatibility, matching
    the RSS collector's normalization rules.
    """
    title = entry.get("title")
    url = entry.get("url")

    return bool(
        (isinstance(title, str) and title.strip())
        or
        (isinstance(url, str) and url.strip())
    )


def parse_entry_published_at(
    entry: dict[str, Any],
) -> datetime | None:
    """
    Parse the normalized publication timestamp.
    """
    return parse_iso_datetime(
        entry.get("published_at")
    )


# ------------------------------------------------------------------ #
# Processing
# ------------------------------------------------------------------ #

def process_tech(
    start: datetime,
    end: datetime,
    covered_ist_day: str,
    reporting_date: str | None = None,
) -> dict[str, Any]:
    """
    Process RSS/Atom data for exactly one TechPulse edition.

    RSS lookback:
        Eligible publication interval:

            [start - 48h, end)

    where start/end are the exact edition window boundaries.

    The lookback is intentionally bounded and deterministic. It does not
    attempt to reconstruct arbitrary historical feed state.
    """

    if reporting_date is None:
        reporting_date = (
            parse_ist_date(covered_ist_day)
            + timedelta(days=1)
        ).isoformat()

    try:
        parse_ist_date(covered_ist_day)
        parse_ist_date(reporting_date)
    except ValueError as exc:
        raise ValueError(
            f"Invalid technology processing date: {exc}"
        ) from exc

    tech_path = dated_file_for(
        TECH_DIR,
        reporting_date,
    )

    (
        tech_data,
        all_entries,
        failures,
        source_status,
    ) = load_rss_source(
        tech_path,
        reporting_date,
    )

    # The raw collector has one collection timestamp for the entire
    # source file. This is the strongest observation timestamp TechPulse
    # actually has and is therefore exposed in normalized metadata.
    collection_observed_at = (
        (tech_data.get("meta") or {}).get("collectedAt")
        if isinstance(tech_data, dict)
        else None
    )

    parsed_collection_time = parse_iso_datetime(
        collection_observed_at
    )

    lookback_start = (
        start
        - timedelta(hours=LOOKBACK_HOURS)
    )

    eligible_entries: list[dict[str, Any]] = []

    invalid_identity_count = 0
    invalid_timestamp_count = 0
    seen_keys: set[str] = set()

    for entry in all_entries:
        if not valid_entry_identity(entry):
            invalid_identity_count += 1
            continue

        published = parse_entry_published_at(
            entry
        )

        if published is None:
            # We cannot reliably place an entry into the reporting
            # window without a parseable publication timestamp.
            invalid_timestamp_count += 1
            continue

        if not (
            lookback_start
            <= published
            < end
        ):
            continue

        # Deduplicate at the normalized-processing layer as a defense
        # against legacy/raw files that may contain duplicate entries.
        guid = entry.get("guid")
        url = entry.get("url")
        title = entry.get("title")

        identity = (
            str(guid).strip()
            if isinstance(guid, str) and guid.strip()
            else
            str(url).strip()
            if isinstance(url, str) and url.strip()
            else
            str(title).strip()
        )

        if identity in seen_keys:
            continue

        seen_keys.add(identity)

        enriched = dict(entry)

        # This is the source-level observation timestamp, not an
        # invented per-entry timestamp. It tells downstream consumers
        # when this feed snapshot was collected.
        if parsed_collection_time is not None:
            enriched["observed_at"] = (
                parsed_collection_time.isoformat()
            )
        else:
            enriched["observed_at"] = None

        eligible_entries.append(
            enriched
        )

    failures += (
        invalid_identity_count
        + invalid_timestamp_count
    )

    if invalid_identity_count:
        print(
            f"  WARNING: {invalid_identity_count} entries lacked "
            "usable identity fields"
        )

    if invalid_timestamp_count:
        print(
            f"  WARNING: {invalid_timestamp_count} entries lacked "
            "a parseable publication timestamp"
        )

    # -------------------------------------------------------------- #
    # Deterministic ordering
    # -------------------------------------------------------------- #

    eligible_entries.sort(
        key=lambda entry: (
            entry.get("published_at") or "",
            entry.get("url") or "",
            entry.get("title") or "",
        ),
        reverse=True,
    )

    # -------------------------------------------------------------- #
    # Aggregates
    # -------------------------------------------------------------- #

    categories: dict[str, int] = {}
    sources: dict[str, int] = {}

    for entry in eligible_entries:
        category = (
            entry.get("feed_category")
            or "tech"
        )

        source = (
            entry.get("feed_source")
            or "Unknown"
        )

        categories[category] = (
            categories.get(category, 0) + 1
        )

        sources[source] = (
            sources.get(source, 0) + 1
        )

    # -------------------------------------------------------------- #
    # Source health
    # -------------------------------------------------------------- #

    if failures > 0:
        final_status = (
            "partial"
            if all_entries
            else "failed"
        )
    elif not eligible_entries:
        # The source itself may have returned records, but none were
        # eligible for this edition's publication window. That is a
        # legitimate EMPTY edition for this processor.
        final_status = "empty"
    else:
        final_status = "success"

    # Preserve structural source failure.
    if source_status == "failed" and not all_entries:
        final_status = "failed"

    processed_at = derive_processed_at(
        [tech_path]
    )

    return {
        "meta": {
            "processedAt": processed_at,
            "reportingDate": reporting_date,
            "coveredIstDay": covered_ist_day,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "lookbackHours": LOOKBACK_HOURS,
                "publicationInterval": {
                    "start": lookback_start.isoformat(),
                    "end": end.isoformat(),
                },
            },
            "observation": {
                "sourceCollectedAt": (
                    parsed_collection_time.isoformat()
                    if parsed_collection_time
                    else None
                ),
                "observationModel": (
                    "feed_snapshot_collection_time"
                ),
            },
            "sourceFiles": {
                "tech": (
                    tech_path.name
                    if tech_path
                    else None
                ),
            },
            "sources": {
                "rss": {
                    "status": final_status,
                    "total": len(all_entries),
                    "inWindow": len(eligible_entries),
                    "failures": failures,
                },
            },
        },
        "summary": {
            "total": len(eligible_entries),
            "categories": categories,
            "sources": sources,
            "lookbackHours": LOOKBACK_HOURS,
        },
        "entries": eligible_entries[:30],
    }


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Process technology/RSS data."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date "
            "(YYYY-MM-DD, IST edition)."
        ),
    )

    parser.add_argument(
        "--start",
        help=(
            "Window start (ISO 8601). Overrides --date."
        ),
    )

    parser.add_argument(
        "--end",
        help=(
            "Window end (ISO 8601, exclusive). Overrides --date."
        ),
    )

    args = parser.parse_args()

    print()
    print(
        "TechPulse — Tech/RSS Processor"
    )
    print("=" * 32)

    try:
        (
            start,
            end,
            covered_ist_day,
            reporting_date,
        ) = resolve_window(
            args.date,
            args.start,
            args.end,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        f"Reporting date: {reporting_date}"
    )
    print(
        f"Covered IST day: {covered_ist_day}"
    )
    print(
        f"Window: {start.isoformat()} -> "
        f"{end.isoformat()} (end exclusive)"
    )
    print(
        f"RSS lookback  : {LOOKBACK_HOURS} hours"
    )
    print()

    try:
        result = process_tech(
            start,
            end,
            covered_ist_day,
            reporting_date,
        )

        output_path = (
            NORMALIZED_DIR
            / "tech.json"
        )

        save_json(
            result,
            output_path,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    summary = result["summary"]
    rss_source = (
        result["meta"]["sources"]["rss"]
    )

    print()
    print("Processing completed.")
    print(
        f"In eligible window : "
        f"{summary['total']} entries"
    )
    print(
        f"RSS status         : "
        f"{rss_source['status']}"
    )
    print(
        f"Collector failures : "
        f"{rss_source['failures']}"
    )
    print(
        f"Output             : "
        f"{output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
