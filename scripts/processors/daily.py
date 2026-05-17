#!/usr/bin/env python3

"""
TechPulse — Daily Snapshot Processor

Creates the daily snapshot that becomes part of the historical archive.
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
    PROJECT_ROOT,
    DATA_DIR,
)

NORMALIZED_DIR = DATA_DIR / "normalized"
DAILY_DIR = DATA_DIR / "daily"


def load_normalized(name: str) -> dict[str, Any] | None:
    """Load a normalized data file."""
    path = NORMALIZED_DIR / f"{name}.json"
    return load_json(path)


def process_daily(
    snapshot_date: datetime | None = None,
) -> dict[str, Any]:
    """Create a daily snapshot from all normalized sources."""

    if snapshot_date is None:
        # Use previous UTC day
        snapshot_date = utc_now() - timedelta(days=1)
    snapshot_date = snapshot_date.replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"Creating daily snapshot for {snapshot_date.date().isoformat()}...")

    # Define window (entire UTC day)
    window_start = snapshot_date
    window_end = snapshot_date + timedelta(days=1) - timedelta(seconds=1)

    # Load all normalized data
    security = load_normalized("security")
    releases = load_normalized("releases")
    opensource = load_normalized("opensource")
    tech = load_normalized("tech")

    # Extract counts
    security_summary = security.get("summary", {}) if security else {}
    releases_summary = releases.get("summary", {}) if releases else {}
    opensource_summary = opensource.get("summary", {}) if opensource else {}
    tech_summary = tech.get("summary", {}) if tech else {}

    # Build source status
    sources = {}
    for name, data in [("nvd", security), ("cisa", security), ("github", releases), ("rss", tech)]:
        if data:
            src = data.get("meta", {}).get("sources", {}).get(name, {})
            sources[name] = {
                "status": src.get("status", "unknown"),
                "total": src.get("total", 0),
                "inWindow": src.get("inWindow", 0),
            }
        else:
            sources[name] = {"status": "missing", "total": 0, "inWindow": 0}

    # Build snapshot
    snapshot = {
        "date": snapshot_date.date().isoformat(),
        "generatedAt": utc_now().isoformat(),
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "snapshot": {
            "cves": security_summary.get("total", 0),
            "knownExploited": security_summary.get("knownExploited", 0),
            "releases": releases_summary.get("total", 0),
            "projects": opensource_summary.get("totalTracked", 0),
            "techEntries": tech_summary.get("total", 0),
        },
        "security": {
            "severity": security_summary.get("severity", {}),
            "latest": security.get("latest", []) if security else [],
        },
        "releases": {
            "categories": releases_summary.get("categories", {}),
            "recent": releases.get("releases", [])[:10] if releases else [],
        },
        "opensource": {
            "topProjects": opensource.get("topProjects", []) if opensource else [],
        },
        "technology": {
            "categories": tech_summary.get("categories", {}),
            "recent": tech.get("entries", [])[:10] if tech else [],
        },
        "sources": sources,
    }

    return snapshot


def save_daily_snapshot(snapshot: dict[str, Any]) -> Path:
    """Save daily snapshot to archive."""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = snapshot["date"]
    output_path = DAILY_DIR / f"{date_str}.json"
    save_json(snapshot, output_path)
    return output_path


def main() -> int:
    """Main entry point for daily snapshot processor."""
    import argparse
    parser = argparse.ArgumentParser(description="Create daily snapshot.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD)")
    args = parser.parse_args()

    snapshot_date = parse_iso_datetime(args.date) if args.date else None

    print()
    print("TechPulse — Daily Snapshot Processor")
    print("=" * 32)
    print()

    try:
        snapshot = process_daily(snapshot_date)
        output_path = save_daily_snapshot(snapshot)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print()
    print("Daily snapshot created successfully.")
    print(f"Date: {snapshot['date']}")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())