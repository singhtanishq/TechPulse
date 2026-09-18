#!/usr/bin/env python3

"""
TechPulse — Open Source Processor

Normalizes GitHub repository metadata into the application-ready
open-source dataset.

Daily growth policy (documented):
    Star growth is only computed when a previous dated observation for
    the same repository exists (i.e. an earlier data/opensource/
    YYYY-MM-DD.json file). Without a real prior observation the value
    is null and the frontend must show it as unavailable — never a
    fabricated number.

Output:
    data/normalized/opensource.json
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
    latest_dated_file,
    load_json,
    save_json,
    derive_processed_at,
    status_from_counts,
    utc_now,
)

REPO_META_DIR = DATA_DIR / "opensource"
NORMALIZED_DIR = DATA_DIR / "normalized"


def resolve_snapshot_date(date_arg: str | None) -> str:
    if date_arg:
        try:
            datetime.strptime(date_arg, "%Y-%m-%d")
            return date_arg
        except ValueError:
            raise SystemExit("--date must be in YYYY-MM-DD format.")
    day = (utc_now() - timedelta(days=1)).date()
    return day.isoformat()


def previous_observation_stars() -> dict[str, int]:
    """
    Build {full_name: stars} from the second-newest dated observation.

    Returns an empty mapping when fewer than two dated files exist, in
    which case growth is reported as unavailable rather than invented.
    """
    if not REPO_META_DIR.exists():
        return {}
    files = sorted(
        (f for f in REPO_META_DIR.glob("*.json") if f.is_file()),
        key=lambda f: f.stem,
        reverse=True,
    )
    dated = []
    for f in files:
        try:
            datetime.strptime(f.stem, "%Y-%m-%d")
            dated.append(f)
        except ValueError:
            continue
    if len(dated) < 2:
        return {}

    prior = load_json(dated[1])
    if not prior:
        return {}

    return {
        repo.get("full_name"): repo.get("stars") or 0
        for repo in prior.get("repositories", [])
        if isinstance(repo, dict) and repo.get("full_name")
    }


def process_opensource(snapshot_date: str) -> dict[str, Any]:
    """Process open-source repository metadata."""

    repos_path = latest_dated_file(REPO_META_DIR)

    print("Loading repository metadata...")
    repos_data = load_json(repos_path) if repos_path else None
    if not repos_data:
        print("  WARNING: no repository metadata available")
        repos: list[dict[str, Any]] = []
        failures = 1
    else:
        repos = [r for r in repos_data.get("repositories", []) if isinstance(r, dict)]
        collector_failures = repos_data.get("meta", {}).get("failures", []) or []
        failures = len(collector_failures)
        print(f"  Loaded {len(repos)} repositories from {repos_path.name}")

    prior_stars = previous_observation_stars()
    growth_basis = "previous_observation" if prior_stars else "unavailable"

    for repo in repos:
        full_name = repo.get("full_name")
        stars = repo.get("stars")
        if growth_basis == "previous_observation" and full_name in prior_stars and stars is not None:
            repo["daily_growth"] = stars - prior_stars[full_name]
            repo["growth_available"] = True
        else:
            repo["daily_growth"] = None
            repo["growth_available"] = False

    # Deterministic ranking: stars descending, then full_name ascending.
    ranked = sorted(
        repos,
        key=lambda r: (-(r.get("stars") or 0), r.get("full_name") or ""),
    )
    for i, repo in enumerate(ranked):
        repo["rank"] = i + 1

    languages: dict[str, int] = {}
    for repo in repos:
        lang = repo.get("language") or "Unknown"
        languages[lang] = languages.get(lang, 0) + 1

    status = status_from_counts(len(repos), len(repos), failures)
    processed_at = derive_processed_at([repos_path])

    return {
        "meta": {
            "processedAt": processed_at,
            "snapshotDate": snapshot_date,
            "sourceFiles": {
                "opensource": repos_path.name if repos_path else None,
            },
            "sources": {
                "github": {
                    "status": status,
                    "total": len(repos),
                    "inWindow": len(repos),
                    "failures": failures,
                },
            },
        },
        "summary": {
            "totalTracked": len(repos),
            "languages": languages,
            "growthBasis": growth_basis,
        },
        "topProjects": ranked[:10],
        "allProjects": ranked,
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Process open-source repository data.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD, UTC).")
    args = parser.parse_args()

    snapshot_date = resolve_snapshot_date(args.date)

    print()
    print("TechPulse — Open Source Processor")
    print("=" * 32)
    print(f"Snapshot date: {snapshot_date}")
    print()

    try:
        result = process_opensource(snapshot_date)
        output_path = NORMALIZED_DIR / "opensource.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Processing completed.")
    print(f"Tracked repositories: {result['summary']['totalTracked']}")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
