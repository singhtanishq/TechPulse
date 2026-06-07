#!/usr/bin/env python3

"""
TechPulse — History Processor

Builds the historical archive index from daily snapshots.

Behavior:
    - Discovers every dated snapshot in data/daily/.
    - Invalid or malformed snapshot files are skipped with a warning
      (one bad file never destroys the archive view).
    - Duplicate dates are impossible by filename; the newest file for
      a date wins.

Output:
    data/normalized/history.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import DATA_DIR, load_json, save_json, derive_processed_at

DAILY_DIR = DATA_DIR / "daily"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_all_snapshots() -> tuple[list[dict[str, Any]], list[str]]:
    """Load all dated snapshots, newest first. Returns (snapshots, warnings)."""

    warnings: list[str] = []
    by_date: dict[str, dict[str, Any]] = {}

    if not DAILY_DIR.exists():
        return [], ["data/daily/ does not exist yet"]

    for path in DAILY_DIR.glob("*.json"):
        try:
            datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError:
            warnings.append(f"Skipping non-dated file: {path.name}")
            continue

        data = load_json(path)
        if not data:
            warnings.append(f"Skipping invalid snapshot: {path.name}")
            continue

        if "date" not in data or "snapshot" not in data:
            warnings.append(f"Skipping snapshot missing required fields: {path.name}")
            continue

        # Newest file for a date wins (regenerations overwrite by design).
        by_date[data["date"]] = data

    snapshots = sorted(by_date.values(), key=lambda s: s.get("date", ""), reverse=True)
    return snapshots, warnings


def build_history_index(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the simplified history index consumed by the frontend."""
    history = []
    for snap in snapshots:
        counts = snap.get("snapshot", {})
        history.append({
            "date": snap.get("date"),
            "cves": counts.get("cves", 0),
            "knownExploited": counts.get("knownExploited", 0),
            "kevAdded": counts.get("kevAdded", 0),
            "releases": counts.get("releases", 0),
            "projects": counts.get("projects", 0),
            "techEntries": counts.get("techEntries", 0),
        })
    return history


def process_history() -> dict[str, Any]:
    """Process the historical archive."""

    print("Loading daily snapshots...")
    snapshots, warnings = load_all_snapshots()

    for warning in warnings:
        print(f"  WARNING: {warning}")

    print(f"  Found {len(snapshots)} valid snapshots")

    # Deterministic processedAt from the newest snapshot's generatedAt.
    newest_path = None
    if snapshots:
        candidate = DAILY_DIR / f"{snapshots[0].get('date')}.json"
        if candidate.exists():
            newest_path = candidate

    processed_at = derive_processed_at([newest_path]) if newest_path else (
        datetime.now(timezone.utc).isoformat()
    )

    history_index = build_history_index(snapshots)
    latest = snapshots[0] if snapshots else None

    return {
        "meta": {
            "processedAt": processed_at,
            "totalSnapshots": len(snapshots),
            "warnings": warnings,
        },
        "history": history_index,
        "latest": {
            "date": latest.get("date") if latest else None,
            "snapshot": latest.get("snapshot", {}) if latest else {},
        },
    }


def main() -> int:

    print()
    print("TechPulse — History Processor")
    print("=" * 32)
    print()

    try:
        result = process_history()
        output_path = NORMALIZED_DIR / "history.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Processing completed.")
    print(f"Snapshots: {result['meta']['totalSnapshots']}")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
