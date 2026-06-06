#!/usr/bin/env python3

"""
TechPulse — Releases Processor

Normalizes GitHub release records into the application-ready
releases dataset for the snapshot window.

Output:
    data/normalized/releases.json
"""

from __future__ import annotations

import argparse
import re
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

RELEASES_DIR = DATA_DIR / "releases"
NORMALIZED_DIR = DATA_DIR / "normalized"

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def resolve_window(start_arg: str | None, end_arg: str | None) -> tuple[datetime, datetime]:
    end = parse_iso_datetime(end_arg) if end_arg else None
    start = parse_iso_datetime(start_arg) if start_arg else None

    if end is None:
        day = (utc_now() - timedelta(days=1)).date()
        end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1) - timedelta(milliseconds=1)
    if start is None:
        start = end - timedelta(days=1) + timedelta(milliseconds=1)

    return start, end


def release_kind(version: str) -> str:
    """Classify a version string as major / minor / patch / other."""
    match = VERSION_RE.match(version or "")
    if not match:
        return "other"
    major, minor, patch = (int(g) for g in match.groups())
    if minor == 0 and patch == 0:
        return "major"
    if patch == 0:
        return "minor"
    return "patch"


def process_releases(start: datetime, end: datetime) -> dict[str, Any]:
    """Process releases data."""

    releases_path = latest_dated_file(RELEASES_DIR)

    print("Loading releases data...")
    releases_data = load_json(releases_path) if releases_path else None
    if not releases_data:
        print("  WARNING: no releases data available")
        all_releases: list[dict[str, Any]] = []
        failures = 1
    else:
        all_releases = [r for r in releases_data.get("releases", []) if isinstance(r, dict)]
        collector_failures = releases_data.get("meta", {}).get("failures", []) or []
        failures = len(collector_failures)
        print(f"  Loaded {len(all_releases)} releases from {releases_path.name}")

    window_releases = []
    for rel in all_releases:
        published = parse_iso_datetime(rel.get("published_at"))
        if published and start <= published <= end:
            enriched = dict(rel)
            enriched["kind"] = release_kind(rel.get("version", ""))
            enriched["relative_date"] = format_relative_date(published, now=utc_now())
            window_releases.append(enriched)

    # Deterministic ordering: published descending, then repository, then version.
    window_releases.sort(
        key=lambda r: (
            r.get("published_at") or "",
            r.get("repository") or "",
            r.get("version") or "",
        ),
        reverse=True,
    )

    categories = {"major": 0, "minor": 0, "patch": 0, "other": 0}
    for rel in window_releases:
        categories[rel["kind"]] += 1

    status = status_from_counts(len(all_releases), len(window_releases), failures)
    processed_at = derive_processed_at([releases_path])

    return {
        "meta": {
            "processedAt": processed_at,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "sourceFiles": {
                "releases": releases_path.name if releases_path else None,
            },
            "sources": {
                "github": {
                    "status": status,
                    "total": len(all_releases),
                    "inWindow": len(window_releases),
                    "failures": failures,
                },
            },
        },
        "summary": {
            "total": len(window_releases),
            "categories": categories,
        },
        "releases": window_releases[:50],
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Process GitHub releases data.")
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
    print("TechPulse — Releases Processor")
    print("=" * 32)
    print(f"Window: {start.isoformat()} -> {end.isoformat()}")
    print()

    try:
        result = process_releases(start, end)
        output_path = NORMALIZED_DIR / "releases.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Processing completed.")
    print(f"In window: {result['summary']['total']} releases")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
