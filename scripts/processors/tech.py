#!/usr/bin/env python3

"""
TechPulse — Technology Processor

Normalizes RSS/Atom entries into the application-ready technology
dataset for the snapshot window.

Output:
    data/normalized/tech.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (
    DATA_DIR,
    latest_dated_file,
    load_json,
    parse_iso_datetime,
    save_json,
    derive_processed_at,
    format_relative_date,
    status_from_counts,
    utc_now,
)

TECH_DIR = DATA_DIR / "tech"
NORMALIZED_DIR = DATA_DIR / "normalized"


def resolve_window(start_arg: str | None, end_arg: str | None) -> tuple[datetime, datetime]:
    end = parse_iso_datetime(end_arg) if end_arg else None
    start = parse_iso_datetime(start_arg) if start_arg else None

    if end is None:
        day = (utc_now() - timedelta(days=1)).date()
        end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1) - timedelta(milliseconds=1)
    if start is None:
        start = end - timedelta(days=1) + timedelta(milliseconds=1)

    return start, end


def process_tech(start: datetime, end: datetime) -> dict[str, Any]:
    """Process technology/RSS data.

    Window policy (documented):
        RSS/Atom feeds are ephemeral — entries rotate out of a feed
        within roughly 1-3 days, so items observed for a snapshot day
        may carry publication timestamps slightly before that day.
        The technology window therefore applies a 48-hour lookback
        before the snapshot day start: an entry counts if it was
        published no later than the end of the snapshot day and was
        still observable at collection time. This is bounded (no
        unbounded history) and deterministic per snapshot date.
    """

    tech_path = latest_dated_file(TECH_DIR)

    print("Loading tech/RSS data...")
    tech_data = load_json(tech_path) if tech_path else None
    if not tech_data:
        print("  WARNING: no tech data available")
        all_entries: list[dict[str, Any]] = []
        failures = 1
    else:
        all_entries = [e for e in tech_data.get("entries", []) if isinstance(e, dict)]
        collector_failures = tech_data.get("meta", {}).get("failures", []) or []
        failures = len(collector_failures)
        print(f"  Loaded {len(all_entries)} entries from {tech_path.name}")

    lookback_start = start - timedelta(hours=48)

    window_entries = []
    for entry in all_entries:
        published = parse_iso_datetime(entry.get("published_at"))
        if published and lookback_start <= published <= end:
            enriched = dict(entry)
            enriched["relative_date"] = format_relative_date(published, now=utc_now())
            window_entries.append(enriched)

    # Deterministic ordering: published descending, then URL, then title.
    window_entries.sort(
        key=lambda e: (
            e.get("published_at") or "",
            e.get("url") or "",
            e.get("title") or "",
        ),
        reverse=True,
    )

    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    for entry in window_entries:
        cat = entry.get("feed_category") or "tech"
        src = entry.get("feed_source") or "Unknown"
        categories[cat] = categories.get(cat, 0) + 1
        sources[src] = sources.get(src, 0) + 1

    status = status_from_counts(len(all_entries), len(window_entries), failures)
    processed_at = derive_processed_at([tech_path])

    return {
        "meta": {
            "processedAt": processed_at,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "sourceFiles": {
                "tech": tech_path.name if tech_path else None,
            },
            "sources": {
                "rss": {
                    "status": status,
                    "total": len(all_entries),
                    "inWindow": len(window_entries),
                    "failures": failures,
                },
            },
        },
        "summary": {
            "total": len(window_entries),
            "categories": categories,
            "sources": sources,
        },
        "entries": window_entries[:30],
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Process technology/RSS data.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD, UTC).")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC). Overrides --date.")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC). Overrides --date.")
    args = parser.parse_args()

    if args.start and args.end:
        start = parse_iso_datetime(args.start)
        end = parse_iso_datetime(args.end)
        if start is None or end is None:
            parser.error("Invalid --start/--end datetime.")
    else:
        if args.date:
            try:
                day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                parser.error("--date must be in YYYY-MM-DD format.")
        else:
            day = (utc_now() - timedelta(days=1)).date()
            day = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        start = day
        end = day + timedelta(days=1) - timedelta(milliseconds=1)

    print()
    print("TechPulse — Tech/RSS Processor")
    print("=" * 32)
    print(f"Window: {start.isoformat()} -> {end.isoformat()}")
    print()

    try:
        result = process_tech(start, end)
        output_path = NORMALIZED_DIR / "tech.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Processing completed.")
    print(f"In window: {result['summary']['total']} entries")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
