#!/usr/bin/env python3

"""
TechPulse — Archive Generator

Generates the historical archive data (generated/archive.json) from
the daily snapshots for the History page.

Determinism:
    generatedAt is derived from the newest snapshot's generatedAt.

Output:
    generated/archive.json
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
    GENERATED_DIR,
    load_json,
    parse_iso_datetime,
    save_json,
    utc_now,
)

DAILY_DIR = DATA_DIR / "daily"


def load_all_snapshots() -> list[dict[str, Any]]:
    """Load all valid dated snapshots, newest first."""
    by_date: dict[str, dict[str, Any]] = {}
    if not DAILY_DIR.exists():
        return []
    for path in DAILY_DIR.glob("*.json"):
        try:
            datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError:
            continue
        data = load_json(path)
        if data and data.get("date"):
            by_date[data["date"]] = data
    return sorted(by_date.values(), key=lambda s: s.get("date", ""), reverse=True)


def generate_archive() -> dict[str, Any]:
    """Generate the complete archive dataset."""

    print("Loading daily snapshots...")
    snapshots = load_all_snapshots()
    print(f"  Found {len(snapshots)} snapshots")

    generated_at = None
    for snap in snapshots:
        stamp = parse_iso_datetime(snap.get("generatedAt"))
        if stamp and (generated_at is None or stamp > generated_at):
            generated_at = stamp
    if generated_at is None:
        day = (utc_now() - timedelta(days=1)).date()
        generated_at = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)

    archive = []
    for snap in snapshots:
        archive.append({
            "date": snap.get("date"),
            "snapshot": snap.get("snapshot", {}),
            "security": {
                "severity": (snap.get("security") or {}).get("severity", {}),
            },
            "releases": {
                "categories": (snap.get("releases") or {}).get("categories", {}),
                "recent": (snap.get("releases") or {}).get("recent", []),
            },
            "opensource": {
                "topProjects": (snap.get("opensource") or {}).get("topProjects", []),
            },
            "technology": {
                "categories": (snap.get("technology") or {}).get("categories", {}),
                "recent": (snap.get("technology") or {}).get("recent", []),
            },
            "sources": snap.get("sources", {}),
        })

    return {
        "meta": {
            "generatedAt": generated_at.isoformat(),
            "totalSnapshots": len(snapshots),
        },
        "archive": archive,
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Generate the historical archive data.")
    args = parser.parse_args()

    print()
    print("TechPulse — Archive Generator")
    print("=" * 32)
    print()

    try:
        data = generate_archive()
        output_path = GENERATED_DIR / "archive.json"
        save_json(data, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Generation completed.")
    print(f"Snapshots: {data['meta']['totalSnapshots']}")
    print(f"Output   : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
