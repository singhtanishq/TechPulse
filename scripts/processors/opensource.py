#!/usr/bin/env python3

"""
TechPulse — Open Source Processor

Normalizes GitHub repository metadata into the application-ready
open-source dataset.

Reporting-date semantics:
    - A reporting date is an India calendar date (Asia/Kolkata).
    - A date-specific processor may consume ONLY the exact matching
      data/opensource/YYYY-MM-DD.json source file.
    - No cross-date fallback is permitted.

Daily growth policy:
    - Growth is calculated only against the immediately preceding
      reporting date.
    - If that exact previous reporting-date observation does not exist,
      growth is unavailable.
    - Missing star values remain missing; they are never converted to
      fabricated zero values.

Output:
    data/normalized/opensource.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (
    DATA_DIR,
    NORMALIZED_DIR,
    dated_file_for,
    derive_processed_at,
    ist_today,
    load_json,
    parse_ist_date,
    save_json,
    status_from_counts,
)

REPO_META_DIR = DATA_DIR / "opensource"


# ================================================================
# Date handling
# ================================================================

def resolve_snapshot_date(
    date_arg: str | None,
) -> str:
    """Resolve and validate the requested reporting date."""
    if date_arg:
        try:
            parse_ist_date(date_arg)
        except (TypeError, ValueError):
            raise SystemExit(
                "--date must be in YYYY-MM-DD format."
            )

        return date_arg

    return ist_today()


def previous_reporting_date(
    snapshot_date: str,
) -> str:
    """Return the immediately preceding reporting date."""
    return (
        parse_ist_date(snapshot_date)
        - timedelta(days=1)
    ).isoformat()


# ================================================================
# Source helpers
# ================================================================

def _failure_count(
    failures: Any,
) -> int:
    """Return a normalized collector failure count."""
    if failures is None:
        return 0

    if isinstance(failures, list):
        return len(failures)

    if isinstance(failures, bool):
        return int(failures)

    if isinstance(failures, int):
        return max(0, failures)

    return 1


def _validate_source_metadata(
    data: dict[str, Any],
    snapshot_date: str,
) -> None:
    """
    Validate source metadata for a date-specific collection.

    New source files must identify their reporting date explicitly.
    """
    meta = data.get("meta")

    if not isinstance(meta, dict):
        raise ValueError(
            "GitHub repository source is missing its meta object."
        )

    source = meta.get("source")

    if source and source != "GitHub":
        raise ValueError(
            f"GitHub repository source has unexpected source: {source!r}"
        )

    reporting_date = meta.get("reportingDate")

    if not isinstance(reporting_date, str):
        raise ValueError(
            "GitHub repository source is missing meta.reportingDate."
        )

    try:
        parse_ist_date(reporting_date)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "GitHub repository source has invalid meta.reportingDate."
        ) from exc

    if reporting_date != snapshot_date:
        raise ValueError(
            "GitHub repository source reporting date "
            f"{reporting_date} does not match requested "
            f"reporting date {snapshot_date}."
        )


def _load_repository_source(
    snapshot_date: str,
) -> tuple[
    Path | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
    int,
]:
    """
    Load the exact repository source for the requested reporting date.

    Returns:
        (source_path, source_data, repositories, failure_count)
    """
    source_path = dated_file_for(
        REPO_META_DIR,
        snapshot_date,
    )

    if source_path is None:
        print(
            f"  FAILED: exact GitHub repository source file "
            f"for {snapshot_date} is missing"
        )
        return None, None, [], 1

    source_data = load_json(source_path)

    if not isinstance(source_data, dict):
        print(
            f"  FAILED: GitHub repository source "
            f"{source_path.name} is missing or invalid JSON"
        )
        return source_path, None, [], 1

    try:
        _validate_source_metadata(
            source_data,
            snapshot_date,
        )
    except ValueError as exc:
        print(
            f"  FAILED: {exc}"
        )
        return source_path, source_data, [], 1

    repositories_raw = source_data.get(
        "repositories"
    )

    if not isinstance(
        repositories_raw,
        list,
    ):
        print(
            "  FAILED: GitHub repository source "
            "repositories field is missing or invalid"
        )
        return source_path, source_data, [], 1

    repositories = [
        item
        for item in repositories_raw
        if isinstance(item, dict)
    ]

    invalid_items = (
        len(repositories_raw)
        - len(repositories)
    )

    configured_failures = _failure_count(
        source_data.get("meta", {}).get("failures")
    )

    failures = (
        configured_failures
        + invalid_items
    )

    return (
        source_path,
        source_data,
        repositories,
        failures,
    )


def _load_previous_stars(
    snapshot_date: str,
) -> dict[str, int | float]:
    """
    Load star counts from ONLY the immediately preceding reporting date.

    Never search further backward: doing so would create a false
    day-over-day comparison.
    """
    previous_date = previous_reporting_date(
        snapshot_date
    )

    previous_path = dated_file_for(
        REPO_META_DIR,
        previous_date,
    )

    if previous_path is None:
        return {}

    previous_data = load_json(
        previous_path
    )

    if not isinstance(previous_data, dict):
        return {}

    previous_meta = previous_data.get("meta")

    if not isinstance(previous_meta, dict):
        return {}

    previous_reporting = previous_meta.get(
        "reportingDate"
    )

    if previous_reporting != previous_date:
        return {}

    previous_repositories = previous_data.get(
        "repositories"
    )

    if not isinstance(
        previous_repositories,
        list,
    ):
        return {}

    result: dict[str, int | float] = {}

    for repo in previous_repositories:
        if not isinstance(repo, dict):
            continue

        full_name = repo.get(
            "full_name"
        )

        stars = repo.get(
            "stars"
        )

        if not isinstance(
            full_name,
            str,
        ) or not full_name.strip():
            continue

        if isinstance(stars, bool):
            continue

        if isinstance(stars, int):
            if stars >= 0:
                result[
                    full_name.strip()
                ] = stars
            continue

        if isinstance(stars, float):
            if stars >= 0:
                result[
                    full_name.strip()
                ] = stars

    return result


# ================================================================
# Repository normalization
# ================================================================

def _normalize_star_value(
    value: Any,
) -> int | float | None:
    """Preserve a valid non-negative numeric star count."""
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value if value >= 0 else None

    if isinstance(value, float):
        return value if value >= 0 else None

    return None


def _repository_identity(
    repo: dict[str, Any],
) -> str:
    """Return the normalized repository identity."""
    value = repo.get(
        "full_name"
    )

    if not isinstance(
        value,
        str,
    ):
        return ""

    return value.strip()


def _normalize_repository(
    repo: dict[str, Any],
    previous_stars: dict[str, int | float],
) -> dict[str, Any] | None:
    """Normalize one repository while preserving missing values."""
    full_name = _repository_identity(
        repo
    )

    if not full_name:
        return None

    normalized = dict(repo)

    normalized["full_name"] = (
        full_name
    )

    stars = _normalize_star_value(
        repo.get("stars")
    )

    normalized["stars"] = stars

    previous = previous_stars.get(
        full_name
    )

    if (
        stars is not None and
        previous is not None
    ):
        normalized["daily_growth"] = (
            stars - previous
        )
        normalized["growth_available"] = True
    else:
        normalized["daily_growth"] = None
        normalized["growth_available"] = False

    return normalized


# ================================================================
# Main processing
# ================================================================

def process_opensource(
    snapshot_date: str,
) -> dict[str, Any]:
    """Process GitHub repository metadata."""

    print(
        "Loading repository metadata..."
    )

    (
        repos_path,
        repos_data,
        raw_repositories,
        failures,
    ) = _load_repository_source(
        snapshot_date
    )

    if repos_path is not None and repos_data is not None:
        print(
            f"  Loaded {len(raw_repositories)} repositories "
            f"from {repos_path.name} "
            f"(status="
            f"{repos_data.get('meta', {}).get('status', 'unknown')}"
            f")"
        )

    previous_stars = _load_previous_stars(
        snapshot_date
    )

    normalized_repositories: list[
        dict[str, Any]
    ] = []

    seen: set[str] = set()

    duplicate_count = 0
    invalid_identity_count = 0

    for repo in raw_repositories:
        normalized = _normalize_repository(
            repo,
            previous_stars,
        )

        if normalized is None:
            invalid_identity_count += 1
            continue

        full_name = normalized[
            "full_name"
        ]

        if full_name in seen:
            duplicate_count += 1
            continue

        seen.add(full_name)

        normalized_repositories.append(
            normalized
        )

    failures += (
        invalid_identity_count
        + duplicate_count
    )

    # ------------------------------------------------------------
    # Deterministic ranking.
    #
    # Repositories with valid star counts rank first, descending.
    # Missing/invalid star counts are placed last.
    # Ties resolve by full_name.
    # ------------------------------------------------------------

    ranked = sorted(
        normalized_repositories,
        key=lambda repo: (
            repo.get("stars") is None,
            -repo["stars"]
            if isinstance(
                repo.get("stars"),
                (int, float),
            )
            and not isinstance(
                repo.get("stars"),
                bool,
            )
            else 0,
            repo.get(
                "full_name",
                "",
            ),
        ),
    )

    for index, repo in enumerate(
        ranked,
        start=1,
    ):
        repo["rank"] = index

    # ------------------------------------------------------------
    # Summary statistics.
    # ------------------------------------------------------------

    languages: dict[str, int] = {}

    repositories_with_stars = 0
    archived_repositories = 0
    growth_observations = 0

    for repo in ranked:
        language = (
            repo.get("language")
            or "Unknown"
        )

        languages[language] = (
            languages.get(language, 0)
            + 1
        )

        if repo.get("stars") is not None:
            repositories_with_stars += 1

        if repo.get("archived") is True:
            archived_repositories += 1

        if repo.get(
            "growth_available"
        ) is True:
            growth_observations += 1

    if previous_stars:
        growth_basis = (
            "previous_reporting_date"
        )
    else:
        growth_basis = "unavailable"

    status_total = len(
        ranked
    )

    status = status_from_counts(
        status_total,
        status_total,
        failures,
    )

    processed_at = derive_processed_at(
        [repos_path]
    )

    return {
        "meta": {
            "processedAt": processed_at,
            "reportingDate": snapshot_date,
            "snapshotDate": snapshot_date,
            "sourceFiles": {
                "opensource": (
                    repos_path.name
                    if repos_path is not None
                    else None
                ),
            },
            "sources": {
                "github": {
                    "status": status,
                    "total": status_total,
                    "inWindow": status_total,
                    "failures": failures,
                },
            },
        },

        "summary": {
            "totalTracked": len(ranked),
            "repositoriesWithStars": (
                repositories_with_stars
            ),
            "archivedRepositories": (
                archived_repositories
            ),
            "growthObservations": (
                growth_observations
            ),
            "growthBasis": growth_basis,
            "languages": languages,
        },

        "topProjects": ranked[:10],
        "allProjects": ranked,
    }


# ================================================================
# CLI
# ================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Process GitHub open-source repository metadata."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date "
            "(YYYY-MM-DD, IST edition)."
        ),
    )

    args = parser.parse_args()

    snapshot_date = resolve_snapshot_date(
        args.date
    )

    print()
    print(
        "TechPulse — Open Source Processor"
    )
    print(
        "=" * 32
    )
    print(
        f"Snapshot date: {snapshot_date}"
    )
    print()

    try:
        result = process_opensource(
            snapshot_date
        )

        output_path = (
            NORMALIZED_DIR
            / "opensource.json"
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

    summary = result[
        "summary"
    ]

    github_status = result[
        "meta"
    ][
        "sources"
    ][
        "github"
    ][
        "status"
    ]

    print()
    print(
        "Processing completed."
    )
    print(
        f"Tracked repositories : "
        f"{summary['totalTracked']}"
    )
    print(
        f"Repositories with stars: "
        f"{summary['repositoriesWithStars']}"
    )
    print(
        f"Growth observations   : "
        f"{summary['growthObservations']}"
    )
    print(
        f"Growth basis          : "
        f"{summary['growthBasis']}"
    )
    print(
        f"GitHub status         : "
        f"{github_status}"
    )
    print(
        f"Output                : "
        f"{output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
