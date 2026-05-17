#!/usr/bin/env python3

"""
TechPulse — Technology/RSS Processor

Processes RSS/Atom feed data into technology intelligence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils import (
    load_json,
    save_json,
    parse_iso_datetime,
    utc_now,
    format_relative_date,
    PROJECT_ROOT,
    DATA_DIR,
)

TECH_DIR = DATA_DIR / "tech"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_latest_tech() -> dict[str, Any] | None:
    """Load the most recent tech/RSS data file."""
    files = list(TECH_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def filter_by_window(entries: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Filter entries by published_at date within window."""
    filtered = []
    for entry in entries:
        pub_str = entry.get("published_at")
        pub_date = parse_iso_datetime(pub_str)
        if pub_date and start <= pub_date <= end:
            filtered.append(entry)
    return filtered


def categorize_entries(entries: list[dict]) -> dict[str, int]:
    """Count entries by feed category."""
    counts = {}
    for entry in entries:
        cat = entry.get("feed_category", "tech")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def enrich_entries(entries: list[dict]) -> list[dict]:
    """Add computed fields to entries."""
    for entry in entries:
        entry["relative_date"] = format_relative_date(entry.get("published_at"))
        # Truncate summary for display
        summary = entry.get("summary", "")
        if len(summary) > 300:
            entry["summary_short"] = summary[:300] + "..."
        else:
            entry["summary_short"] = summary
    return entries


def process_tech(
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Process technology/RSS data."""

    print("Loading tech/RSS data...")
    tech_data = load_latest_tech()
    if not tech_data:
        print("WARNING: No tech/RSS data found")
        all_entries = []
    else:
        all_entries = tech_data.get("entries", [])
        print(f"  Loaded {len(all_entries)} entries")

    # Determine window
    if window_end is None:
        window_end = utc_now()
    if window_start is None:
        window_start = window_end - timedelta(days=1)

    # Filter by window
    window_entries = filter_by_window(all_entries, window_start, window_end)
    print(f"  {len(window_entries)} entries in window")

    # Categorize
    categories = categorize_entries(window_entries)

    # Enrich
    window_entries = enrich_entries(window_entries)

    # Sort by published date descending
    window_entries.sort(
        key=lambda e: e.get("published_at", "") or "",
        reverse=True
    )

    # Build output
    output = {
        "meta": {
            "processedAt": utc_now().isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "sources": {
                "rss": {
                    "status": "success" if tech_data else "missing",
                    "total": len(all_entries),
                    "inWindow": len(window_entries),
                },
            },
        },
        "summary": {
            "total": len(window_entries),
            "categories": categories,
        },
        "entries": window_entries[:30],  # Limit for frontend
    }

    return output


def main() -> int:
    """Main entry point for tech processor."""
    import argparse
    parser = argparse.ArgumentParser(description="Process tech/RSS data.")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC)")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC)")
    args = parser.parse_args()

    window_start = parse_iso_datetime(args.start) if args.start else None
    window_end = parse_iso_datetime(args.end) if args.end else None

    print()
    print("TechPulse — Tech/RSS Processor")
    print("=" * 32)
    print()

    try:
        result = process_tech(window_start, window_end)
        output_path = NORMALIZED_DIR / "tech.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print()
    print("Processing completed successfully.")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())