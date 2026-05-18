#!/usr/bin/env python3

"""
TechPulse — Archive Generator

Generates the historical archive data for the History page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from processors.utils import (
    load_json,
    save_json,
    utc_now,
    PROJECT_ROOT,
    DATA_DIR,
)

DAILY_DIR = DATA_DIR / "daily"
GENERATED_DIR = PROJECT_ROOT / "generated"


def load_all_snapshots() -> list[dict[str, Any]]:
    """Load all daily snapshots, sorted by date descending."""
    files = list(DAILY_DIR.glob("*.json"))
    snapshots = []
    for f in files:
        data = load_json(f)
        if data:
            snapshots.append(data)
    snapshots.sort(key=lambda s: s.get("date", ""), reverse=True)
    return snapshots


def generate_archive() -> dict[str, Any]:
    """Generate the complete archive data."""

    print("Loading daily snapshots...")
    snapshots = load_all_snapshots()
    print(f"  Found {len(snapshots)} snapshots")

    # Build archive entries for frontend
    archive = []
    for snap in snapshots:
        archive.append({
            "date": snap.get("date"),
            "snapshot": snap.get("snapshot", {}),
            "security": {
                "severity": snap.get("security", {}).get("severity", {}),
            },
            "releases": {
                "categories": snap.get("releases", {}).get("categories", {}),
                "count": len(snap.get("releases", {}).get("recent", [])),
            },
            "opensource": {
                "topProjects": snap.get("opensource", {}).get("topProjects", []),
            },
            "technology": {
                "categories": snap.get("technology", {}).get("categories", {}),
                "count": len(snap.get("technology", {}).get("recent", [])),
            },
            "sources": snap.get("sources", {}),
        })

    output = {
        "meta": {
            "generatedAt": utc_now().isoformat(),
            "totalSnapshots": len(snapshots),
        },
        "archive": archive,
    }

    return output


def main() -> int:
    """Main entry point for archive generator."""

    print()
    print("TechPulse — Archive Generator")
    print("=" * 32)
    print()

    try:
        data = generate_archive()
        output_path = GENERATED_DIR / "archive.json"
        save_json(data, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print()
    print("Generation completed successfully.")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())