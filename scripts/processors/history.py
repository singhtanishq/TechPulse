#!/usr/bin/env python3

"""
TechPulse — History Processor

Builds the historical archive view from daily snapshots.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import (
    load_json,
    save_json,
    PROJECT_ROOT,
    DATA_DIR,
)

DAILY_DIR = DATA_DIR / "daily"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_all_snapshots() -> list[dict[str, Any]]:
    """Load all daily snapshots, sorted by date descending."""
    files = list(DAILY_DIR.glob("*.json"))
    snapshots = []
    for f in files:
        data = load_json(f)
        if data:
            snapshots.append(data)
    # Sort by date descending
    snapshots.sort(key=lambda s: s.get("date", ""), reverse=True)
    return snapshots


def build_history_index(snapshots: list[dict]) -> list[dict]:
    """Build simplified history index for frontend."""
    history = []
    for snap in snapshots:
        history.append({
            "date": snap.get("date"),
            "cves": snap.get("snapshot", {}).get("cves", 0),
            "knownExploited": snap.get("snapshot", {}).get("knownExploited", 0),
            "releases": snap.get("snapshot", {}).get("releases", 0),
            "projects": snap.get("snapshot", {}).get("projects", 0),
            "techEntries": snap.get("snapshot", {}).get("techEntries", 0),
        })
    return history


def process_history() -> dict[str, Any]:
    """Process historical archive data."""

    print("Loading daily snapshots...")
    snapshots = load_all_snapshots()
    print(f"  Found {len(snapshots)} snapshots")

    # Build history index
    history_index = build_history_index(snapshots)

    # Get latest snapshot for "current" reference
    latest = snapshots[0] if snapshots else None

    output = {
        "meta": {
            "processedAt": datetime.now(timezone.utc).isoformat(),
            "totalSnapshots": len(snapshots),
        },
        "history": history_index,
        "latest": {
            "date": latest.get("date") if latest else None,
            "snapshot": latest.get("snapshot") if latest else {},
        },
    }

    return output


def main() -> int:
    """Main entry point for history processor."""

    print()
    print("TechPulse — History Processor")
    print("=" * 32)
    print()

    try:
        result = process_history()
        output_path = NORMALIZED_DIR / "history.json"
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