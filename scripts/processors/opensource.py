#!/usr/bin/env python3

"""
TechPulse — Open Source Processor

Processes GitHub repository metadata into open source intelligence.
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

REPO_META_DIR = DATA_DIR / "opensource"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_latest_repos() -> dict[str, Any] | None:
    """Load the most recent repository metadata file."""
    files = list(REPO_META_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def calculate_growth(repos: list[dict]) -> list[dict]:
    """
    Calculate daily star growth for repositories.
    Note: This requires historical data to compute actual growth.
    For now, we return the current stars and mark growth as unavailable.
    """
    for repo in repos:
        repo["daily_growth"] = None
        repo["growth_available"] = False
    return repos


def rank_repositories(repos: list[dict]) -> list[dict]:
    """Rank repositories by stars (descending)."""
    ranked = sorted(repos, key=lambda r: r.get("stars", 0) or 0, reverse=True)
    for i, repo in enumerate(ranked):
        repo["rank"] = i + 1
    return ranked


def categorize_repos(repos: list[dict]) -> dict[str, int]:
    """Count repositories by language/category."""
    counts = {}
    for repo in repos:
        lang = repo.get("language") or "Unknown"
        counts[lang] = counts.get(lang, 0) + 1
    return counts


def process_opensource(
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Process open source data."""

    print("Loading repository metadata...")
    repos_data = load_latest_repos()
    if not repos_data:
        print("WARNING: No repository metadata found")
        repos = []
    else:
        repos = repos_data.get("repositories", [])
        print(f"  Loaded {len(repos)} repositories")

    # Determine window (for metadata)
    if window_end is None:
        window_end = utc_now()
    if window_start is None:
        window_start = window_end - timedelta(days=1)

    # Calculate growth (placeholder - needs historical data)
    repos = calculate_growth(repos)

    # Rank by stars
    ranked_repos = rank_repositories(repos)

    # Categorize
    categories = categorize_repos(repos)

    # Top projects for display
    top_projects = ranked_repos[:10]

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
                    "status": "success" if repos_data else "missing",
                    "total": len(repos),
                },
            },
        },
        "summary": {
            "totalTracked": len(repos),
            "categories": categories,
        },
        "topProjects": top_projects,
        "allProjects": ranked_repos,
    }

    return output


def main() -> int:
    """Main entry point for open source processor."""
    import argparse
    parser = argparse.ArgumentParser(description="Process open source data.")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC)")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC)")
    args = parser.parse_args()

    window_start = parse_iso_datetime(args.start) if args.start else None
    window_end = parse_iso_datetime(args.end) if args.end else None

    print()
    print("TechPulse — Open Source Processor")
    print("=" * 32)
    print()

    try:
        result = process_opensource(window_start, window_end)
        output_path = NORMALIZED_DIR / "opensource.json"
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