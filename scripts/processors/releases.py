#!/usr/bin/env python3

"""
TechPulse — Releases Processor

Processes GitHub releases data into normalized release information.
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
    deduplicate_by_key,
    PROJECT_ROOT,
    DATA_DIR,
)

RELEASES_DIR = DATA_DIR / "releases"
REPO_META_DIR = DATA_DIR / "opensource"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_latest_releases() -> dict[str, Any] | None:
    """Load the most recent releases data file."""
    files = list(RELEASES_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def load_latest_repos() -> dict[str, Any] | None:
    """Load the most recent repository metadata file."""
    files = list(REPO_META_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def filter_releases_by_window(
    releases: list[dict],
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Filter releases by published_at date within window."""
    filtered = []
    for rel in releases:
        pub_str = rel.get("published_at")
        pub_date = parse_iso_datetime(pub_str)
        if pub_date and start <= pub_date <= end:
            filtered.append(rel)
    return filtered


def categorize_releases(releases: list[dict]) -> dict[str, int]:
    """Categorize releases by type (major, minor, patch)."""
    counts = {"major": 0, "minor": 0, "patch": 0, "other": 0}
    for rel in releases:
        version = rel.get("version", "").lstrip("v")
        parts = version.split(".")
        try:
            if len(parts) >= 3:
                major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                if minor == 0 and patch == 0:
                    counts["major"] += 1
                elif patch == 0:
                    counts["minor"] += 1
                else:
                    counts["patch"] += 1
            else:
                counts["other"] += 1
        except ValueError:
            counts["other"] += 1
    return counts


def enrich_releases(releases: list[dict]) -> list[dict]:
    """Add computed fields to releases."""
    for rel in releases:
        rel["relative_date"] = format_relative_date(rel.get("published_at"))
    return releases


def process_releases(
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Process releases data."""

    print("Loading releases data...")
    releases_data = load_latest_releases()
    if not releases_data:
        print("WARNING: No releases data found")
        all_releases = []
    else:
        all_releases = releases_data.get("releases", [])
        print(f"  Loaded {len(all_releases)} releases")

    print("Loading repository metadata...")
    repos_data = load_latest_repos()
    if not repos_data:
        print("WARNING: No repository metadata found")
        repos = []
    else:
        repos = repos_data.get("repositories", [])
        print(f"  Loaded {len(repos)} repositories")

    # Determine window
    if window_end is None:
        window_end = utc_now()
    if window_start is None:
        window_start = window_end - timedelta(days=1)

    # Filter by window
    window_releases = filter_releases_by_window(all_releases, window_start, window_end)
    print(f"  {len(window_releases)} releases in window")

    # Categorize
    categories = categorize_releases(window_releases)

    # Enrich with relative dates
    window_releases = enrich_releases(window_releases)

    # Sort by published date descending
    window_releases.sort(
        key=lambda r: r.get("published_at", "") or "",
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
                "github": {
                    "status": "success" if releases_data else "missing",
                    "totalReleases": len(all_releases),
                    "totalRepos": len(repos),
                    "inWindow": len(window_releases),
                },
            },
        },
        "summary": {
            "total": len(window_releases),
            "categories": categories,
        },
        "releases": window_releases[:50],  # Limit to 50 for frontend
    }

    return output


def main() -> int:
    """Main entry point for releases processor."""
    import argparse
    parser = argparse.ArgumentParser(description="Process releases data.")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC)")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC)")
    args = parser.parse_args()

    window_start = parse_iso_datetime(args.start) if args.start else None
    window_end = parse_iso_datetime(args.end) if args.end else None

    print()
    print("TechPulse — Releases Processor")
    print("=" * 32)
    print()

    try:
        result = process_releases(window_start, window_end)
        output_path = NORMALIZED_DIR / "releases.json"
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