#!/usr/bin/env python3

"""
TechPulse — History Processor

Builds the historical archive index from daily snapshots.

Behavior:
    - Discovers every dated snapshot in data/daily/.
    - Invalid or malformed snapshot files are skipped with a warning.
    - A snapshot's internal "date" must exactly match its filename date.
    - Snapshot count fields must be non-negative integers.
    - Duplicate historical dates are rejected rather than silently
      replacing one snapshot with another.
    - One bad snapshot never destroys the archive view.

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

from processors.utils import (  # noqa: E402
    DATA_DIR,
    derive_processed_at,
    load_json,
    parse_iso_datetime,
    parse_ist_date,
    save_json,
)

DAILY_DIR = DATA_DIR / "daily"
NORMALIZED_DIR = DATA_DIR / "normalized"

SNAPSHOT_COUNT_FIELDS = (
    "cves",
    "knownExploited",
    "kevAdded",
    "releases",
    "projects",
    "techEntries",
)


def _is_valid_date(value: Any) -> bool:
    """Return True only for a real YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        return False

    try:
        parsed = parse_ist_date(value)
    except (TypeError, ValueError):
        return False

    return parsed is not None


def _is_valid_nonnegative_int(
    value: Any,
) -> bool:
    """Return True for integer counts >= 0, excluding booleans."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def validate_snapshot(
    data: Any,
    filename_date: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Validate one daily snapshot.

    Returns:
        (snapshot, error)
    """
    if not isinstance(data, dict):
        return None, "snapshot root must be an object"

    snapshot_date = data.get("date")

    if not _is_valid_date(snapshot_date):
        return (
            None,
            "snapshot date must be a real YYYY-MM-DD date",
        )

    if snapshot_date != filename_date:
        return (
            None,
            f"internal date '{snapshot_date}' does not "
            f"match filename date '{filename_date}'",
        )

    snapshot_counts = data.get("snapshot")

    if not isinstance(snapshot_counts, dict):
        return (
            None,
            "missing or invalid 'snapshot' object",
        )

    for field in SNAPSHOT_COUNT_FIELDS:
        value = snapshot_counts.get(field)

        if not _is_valid_nonnegative_int(value):
            return (
                None,
                f"snapshot.{field} must be a "
                "non-negative integer",
            )

    generated_at = data.get("generatedAt")

    if generated_at is not None:
        if not parse_iso_datetime(generated_at):
            return (
                None,
                "generatedAt must be a valid ISO-8601 "
                "timestamp",
            )

    covered_ist_day = data.get(
        "coveredIstDay"
    )

    if covered_ist_day is not None:
        if not _is_valid_date(
            covered_ist_day
        ):
            return (
                None,
                "coveredIstDay must be a real "
                "YYYY-MM-DD date",
            )

    return data, None


def load_all_snapshots() -> tuple[
    list[dict[str, Any]],
    list[str],
]:
    """
    Load all valid dated snapshots, newest first.

    Invalid files are skipped with warnings. A snapshot is accepted
    only when its internal date agrees with the filename date.
    """

    warnings: list[str] = []
    snapshots: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    if not DAILY_DIR.exists():
        return [], [
            "data/daily/ does not exist yet"
        ]

    for path in sorted(
        DAILY_DIR.glob("*.json")
    ):
        filename_date = path.stem

        if not _is_valid_date(
            filename_date
        ):
            warnings.append(
                f"Skipping non-dated file: "
                f"{path.name}"
            )
            continue

        try:
            data = load_json(path)
        except Exception as exc:
            warnings.append(
                f"Skipping unreadable snapshot "
                f"{path.name}: {exc}"
            )
            continue

        if data is None:
            warnings.append(
                f"Skipping invalid snapshot: "
                f"{path.name}"
            )
            continue

        valid_snapshot, error = (
            validate_snapshot(
                data,
                filename_date,
            )
        )

        if valid_snapshot is None:
            warnings.append(
                f"Skipping snapshot "
                f"{path.name}: {error}"
            )
            continue

        snapshot_date = valid_snapshot[
            "date"
        ]

        if snapshot_date in seen_dates:
            warnings.append(
                f"Skipping duplicate snapshot "
                f"date: {snapshot_date} "
                f"({path.name})"
            )
            continue

        seen_dates.add(
            snapshot_date
        )
        snapshots.append(
            valid_snapshot
        )

    snapshots.sort(
        key=lambda snapshot: snapshot[
            "date"
        ],
        reverse=True,
    )

    return snapshots, warnings


def build_history_index(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the simplified history index consumed by the frontend."""

    history: list[dict[str, Any]] = []

    for snapshot in snapshots:
        counts = snapshot.get(
            "snapshot",
            {}
        )

        if not isinstance(
            counts,
            dict,
        ):
            continue

        history.append(
            {
                "date": snapshot.get(
                    "date"
                ),
                "cves": counts.get(
                    "cves",
                    0,
                ),
                "knownExploited": counts.get(
                    "knownExploited",
                    0,
                ),
                "kevAdded": counts.get(
                    "kevAdded",
                    0,
                ),
                "releases": counts.get(
                    "releases",
                    0,
                ),
                "projects": counts.get(
                    "projects",
                    0,
                ),
                "techEntries": counts.get(
                    "techEntries",
                    0,
                ),
            }
        )

    return history


def _newest_snapshot_path(
    snapshots: list[dict[str, Any]],
) -> Path | None:
    """Resolve the verified path for the newest snapshot."""
    if not snapshots:
        return None

    newest_date = snapshots[0].get(
        "date"
    )

    if not isinstance(
        newest_date,
        str,
    ):
        return None

    candidate = (
        DAILY_DIR
        / f"{newest_date}.json"
    )

    return (
        candidate
        if candidate.is_file()
        else None
    )


def process_history() -> dict[str, Any]:
    """Process the historical archive."""

    print(
        "Loading daily snapshots..."
    )

    snapshots, warnings = (
        load_all_snapshots()
    )

    for warning in warnings:
        print(
            f"  WARNING: {warning}"
        )

    print(
        f"  Found {len(snapshots)} "
        "valid snapshots"
    )

    newest_path = _newest_snapshot_path(
        snapshots
    )

    if newest_path:
        processed_at = derive_processed_at(
            [newest_path]
        )
    else:
        # There is no source timestamp to derive from when the history
        # is completely empty. Keep the normalized output valid while
        # making the fallback explicit.
        processed_at = datetime.now(
            timezone.utc
        ).isoformat()

    history_index = build_history_index(
        snapshots
    )

    latest = (
        snapshots[0]
        if snapshots
        else None
    )

    latest_snapshot = (
        latest.get(
            "snapshot",
            {},
        )
        if latest
        else {}
    )

    if not isinstance(
        latest_snapshot,
        dict,
    ):
        latest_snapshot = {}

    return {
        "meta": {
            "processedAt": processed_at,
            "totalSnapshots": len(
                snapshots
            ),
            "warnings": warnings,
        },
        "history": history_index,
        "latest": {
            "date": (
                latest.get("date")
                if latest
                else None
            ),
            "snapshot": latest_snapshot,
        },
    }


def main() -> int:
    print()
    print(
        "TechPulse — History Processor"
    )
    print("=" * 32)
    print()

    try:
        result = process_history()

        output_path = (
            NORMALIZED_DIR
            / "history.json"
        )

        save_json(
            result,
            output_path,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        "Processing completed."
    )
    print(
        f"Snapshots: "
        f"{result['meta']['totalSnapshots']}"
    )
    print(
        f"Output: {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
