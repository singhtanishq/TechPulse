#!/usr/bin/env python3

"""
TechPulse — Archive Generator

Generates the historical archive data (generated/archive.json) from
validated daily snapshots for the History page.

Integrity:
    - Snapshot filename dates must be valid YYYY-MM-DD dates.
    - A snapshot's internal "date" must exactly match its filename.
    - Required snapshot count fields must be non-negative integers.
    - Malformed snapshots are skipped and recorded in metadata instead
      of contaminating the archive.
    - Future-dated snapshots are retained because this is a complete
      historical archive; the archive itself is not limited to the
      currently requested edition.

Determinism:
    generatedAt is derived from the newest valid snapshot's
    generatedAt. When there are no valid snapshots, generatedAt is null
    rather than being derived from the current wall clock.

Output:
    generated/archive.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    DATA_DIR,
    GENERATED_DIR,
    load_json,
    parse_iso_datetime,
    parse_ist_date,
    save_json,
)


DAILY_DIR = DATA_DIR / "daily"

SNAPSHOT_COUNT_FIELDS = (
    "cves",
    "knownExploited",
    "kevAdded",
    "releases",
    "projects",
    "techEntries",
)


def _is_valid_date(
    value: Any,
) -> bool:
    """Return True only for a real YYYY-MM-DD date."""
    if not isinstance(
        value,
        str,
    ):
        return False

    try:
        parsed = parse_ist_date(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return False

    return parsed is not None


def _is_nonnegative_int(
    value: Any,
) -> bool:
    """Validate a non-negative integer excluding booleans."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _validate_snapshot(
    data: Any,
    filename_date: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Validate a daily snapshot for archive inclusion.

    Returns:
        (snapshot, error)
    """

    if not isinstance(
        data,
        dict,
    ):
        return (
            None,
            "snapshot root must be an object",
        )

    snapshot_date = data.get(
        "date"
    )

    if not _is_valid_date(
        snapshot_date
    ):
        return (
            None,
            "internal date is not a valid YYYY-MM-DD date",
        )

    if snapshot_date != filename_date:
        return (
            None,
            f"internal date '{snapshot_date}' does not "
            f"match filename date '{filename_date}'",
        )

    snapshot_counts = data.get(
        "snapshot"
    )

    if not isinstance(
        snapshot_counts,
        dict,
    ):
        return (
            None,
            "missing or invalid 'snapshot' object",
        )

    for field in SNAPSHOT_COUNT_FIELDS:
        if not _is_nonnegative_int(
            snapshot_counts.get(field)
        ):
            return (
                None,
                f"snapshot.{field} must be a "
                "non-negative integer",
            )

    generated_at = data.get(
        "generatedAt"
    )

    if generated_at is not None and (
        parse_iso_datetime(
            generated_at
        )
        is None
    ):
        return (
            None,
            "generatedAt is not a valid ISO-8601 timestamp",
        )

    covered_ist_day = data.get(
        "coveredIstDay"
    )

    if covered_ist_day is not None and not _is_valid_date(
        covered_ist_day
    ):
        return (
            None,
            "coveredIstDay is not a valid YYYY-MM-DD date",
        )

    return data, None


def load_all_snapshots() -> tuple[
    list[dict[str, Any]],
    list[str],
]:
    """
    Load all valid dated snapshots, newest first.

    Invalid snapshots are skipped and returned as warnings so a single
    bad historical file cannot poison the archive.
    """

    warnings: list[str] = []
    snapshots: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    if not DAILY_DIR.exists():
        return (
            [],
            ["data/daily/ does not exist yet"],
        )

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
            data = load_json(
                path
            )
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

        snapshot, error = _validate_snapshot(
            data,
            filename_date,
        )

        if snapshot is None:
            warnings.append(
                f"Skipping snapshot "
                f"{path.name}: {error}"
            )
            continue

        snapshot_date = snapshot[
            "date"
        ]

        if snapshot_date in seen_dates:
            warnings.append(
                f"Skipping duplicate snapshot date "
                f"{snapshot_date}: {path.name}"
            )
            continue

        seen_dates.add(
            snapshot_date
        )
        snapshots.append(
            snapshot
        )

    snapshots.sort(
        key=lambda snapshot: snapshot[
            "date"
        ],
        reverse=True,
    )

    return (
        snapshots,
        warnings,
    )


def _derive_generated_at(
    snapshots: list[dict[str, Any]],
) -> str | None:
    """
    Derive a deterministic archive generation timestamp.

    No snapshots -> None, deliberately avoiding a wall-clock fallback.
    """

    newest_timestamp = None

    for snapshot in snapshots:
        stamp = parse_iso_datetime(
            snapshot.get(
                "generatedAt"
            )
        )

        if stamp is None:
            continue

        if (
            newest_timestamp is None
            or stamp > newest_timestamp
        ):
            newest_timestamp = stamp

    return (
        newest_timestamp.isoformat()
        if newest_timestamp is not None
        else None
    )


def _safe_dict(
    value: Any,
) -> dict[str, Any]:
    """Return a dictionary or an empty dictionary."""
    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def _safe_list(
    value: Any,
) -> list[Any]:
    """Return a list or an empty list."""
    return (
        value
        if isinstance(
            value,
            list,
        )
        else []
    )


def generate_archive() -> dict[str, Any]:
    """Generate the complete archive dataset."""

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

    archive: list[dict[str, Any]] = []

    for snapshot in snapshots:
        snapshot_security = _safe_dict(
            snapshot.get(
                "security"
            )
        )

        snapshot_releases = _safe_dict(
            snapshot.get(
                "releases"
            )
        )

        snapshot_opensource = _safe_dict(
            snapshot.get(
                "opensource"
            )
        )

        snapshot_technology = _safe_dict(
            snapshot.get(
                "technology"
            )
        )

        archive.append(
            {
                "date": snapshot.get(
                    "date"
                ),
                "snapshot": _safe_dict(
                    snapshot.get(
                        "snapshot"
                    )
                ),
                "security": {
                    "severity": _safe_dict(
                        snapshot_security.get(
                            "severity"
                        )
                    ),
                },
                "releases": {
                    "categories": _safe_dict(
                        snapshot_releases.get(
                            "categories"
                        )
                    ),
                    "recent": _safe_list(
                        snapshot_releases.get(
                            "recent"
                        )
                    ),
                },
                "opensource": {
                    "topProjects": _safe_list(
                        snapshot_opensource.get(
                            "topProjects"
                        )
                    ),
                },
                "technology": {
                    "categories": _safe_dict(
                        snapshot_technology.get(
                            "categories"
                        )
                    ),
                    "recent": _safe_list(
                        snapshot_technology.get(
                            "recent"
                        )
                    ),
                },
                "sources": _safe_dict(
                    snapshot.get(
                        "sources"
                    )
                ),
            }
        )

    generated_at = _derive_generated_at(
        snapshots
    )

    return {
        "meta": {
            "generatedAt": generated_at,
            "totalSnapshots": len(
                snapshots
            ),
            "warnings": warnings,
        },
        "archive": archive,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the historical archive data."
        )
    )

    parser.parse_args()

    print()
    print(
        "TechPulse — Archive Generator"
    )
    print("=" * 32)
    print()

    try:
        data = generate_archive()

        output_path = (
            GENERATED_DIR
            / "archive.json"
        )

        save_json(
            data,
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
        "Generation completed."
    )
    print(
        f"Snapshots: "
        f"{data['meta']['totalSnapshots']}"
    )

    if data["meta"]["warnings"]:
        print(
            f"Warnings : "
            f"{len(data['meta']['warnings'])}"
        )

    print(
        f"Output   : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
