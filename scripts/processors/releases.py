#!/usr/bin/env python3

"""
TechPulse — Releases Processor

Normalizes GitHub release records into the application-ready
releases dataset for the edition's reporting window.

Reporting window:
    The edition for reporting date X (an India calendar day) covers the
    previous IST day [X-1 00:00 IST, X 00:00 IST). Releases are matched
    by their published_at instant against this half-open window.

Output:
    data/normalized/releases.json
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (
    DATA_DIR,
    dated_file_for,
    ist_day_window,
    ist_date_of,
    ist_today,
    latest_dated_file,
    load_json,
    parse_iso_datetime,
    save_json,
    derive_processed_at,
    status_from_counts,
)

RELEASES_DIR = DATA_DIR / "releases"
NORMALIZED_DIR = DATA_DIR / "normalized"

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def resolve_window(
    date_arg: str | None,
    start_arg: str | None,
    end_arg: str | None,
) -> tuple[datetime, datetime, str, str | None]:
    """Resolve (start, end, covered_ist_day, reporting_date)."""
    if start_arg and end_arg:
        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)
        if start is None or end is None:
            raise ValueError("Invalid --start/--end datetime.")
        return start, end, ist_date_of(start), (date_arg or None)

    reporting_date = date_arg or ist_today()
    start, end = ist_day_window(reporting_date)
    return start, end, ist_date_of(start), reporting_date


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


def process_releases(start: datetime, end: datetime, covered_ist_day: str) -> dict[str, Any]:
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
        if published and start <= published < end:
            enriched = dict(rel)
            enriched["kind"] = release_kind(rel.get("version", ""))
            # No relative labels here: the frontend renders live
            # relative dates from the ISO timestamp.
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
            "coveredIstDay": covered_ist_day,
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
    parser.add_argument("--date", help="Reporting date (YYYY-MM-DD, IST edition).")
    parser.add_argument("--start", help="Window start (ISO 8601). Overrides --date.")
    parser.add_argument("--end", help="Window end (ISO 8601, exclusive). Overrides --date.")
    args = parser.parse_args()

    print()
    print("TechPulse — Releases Processor")
    print("=" * 32)

    try:
        start, end, covered_ist_day = resolve_window(args.date, args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Covered IST day: {covered_ist_day}")
    print(f"Window: {start.isoformat()} -> {end.isoformat()} (end exclusive)")
    print()

    try:
        result = process_releases(start, end, covered_ist_day)
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
