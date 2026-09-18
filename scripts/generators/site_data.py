#!/usr/bin/env python3

"""
TechPulse — Site Data Generator

Generates the main frontend data file (generated/data.json) from the
normalized datasets.

Determinism:
    The generation timestamp is derived from the newest processedAt in
    the normalized inputs, so reprocessing identical inputs produces
    byte-identical output. No wall-clock reads occur in this generator.

Output:
    generated/data.json
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
    NORMALIZED_DIR,
    load_json,
    parse_iso_datetime,
    save_json,
    format_relative_date,
    utc_now,
)


def resolve_snapshot_date(date_arg: str | None) -> str:
    if date_arg:
        try:
            datetime.strptime(date_arg, "%Y-%m-%d")
            return date_arg
        except ValueError:
            raise SystemExit("--date must be in YYYY-MM-DD format.")
    day = (utc_now() - timedelta(days=1)).date()
    return day.isoformat()


def truncate(text: str, limit: int = 160) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def format_cve(cve: dict[str, Any]) -> dict[str, Any]:
    """Format an NVD record for frontend display."""
    cvss = cve.get("cvss") or {}
    description = cve.get("description") or ""
    return {
        "id": cve.get("id") or "",
        "title": truncate(description) or "(no description available)",
        "description": truncate(description, 400),
        "severity": cve.get("severity"),
        "cvss_score": cvss.get("score") if cvss else None,
        "cvss_version": cvss.get("version") if cvss else None,
        "published": format_relative_date(cve.get("published")),
        "modified": format_relative_date(cve.get("lastModified")),
        "known_exploited": bool(cve.get("known_exploited")),
        "url": f"https://nvd.nist.gov/vuln/detail/{cve.get('id')}" if cve.get("id") else "",
        "source": "NVD",
    }


def format_release(rel: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": rel.get("project") or "",
        "repository": rel.get("repository") or "",
        "version": rel.get("version") or "",
        "kind": rel.get("kind") or "other",
        "date": rel.get("relative_date") or format_relative_date(rel.get("published_at")),
        "url": rel.get("url") or "",
        "source": rel.get("source") or "GitHub",
    }


def format_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": project.get("rank", 0),
        "name": project.get("name") or "",
        "full_name": project.get("full_name") or "",
        "description": project.get("description") or "",
        "stars": project.get("stars"),
        "daily_growth": project.get("daily_growth"),
        "growth_available": bool(project.get("growth_available")),
        "language": project.get("language") or "",
        "url": project.get("url") or "",
        "source": "GitHub",
    }


def format_tech_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": entry.get("title") or "",
        "url": entry.get("url") or "",
        "source": entry.get("feed_source") or "",
        "category": entry.get("feed_category") or "tech",
        "date": entry.get("relative_date") or format_relative_date(entry.get("published_at")),
        "summary": entry.get("summary") or "",
    }


def generate_site_data(snapshot_date: str) -> dict[str, Any]:
    """Generate the complete frontend dataset."""

    print("Loading normalized data...")

    security = load_json(NORMALIZED_DIR / "security.json")
    releases = load_json(NORMALIZED_DIR / "releases.json")
    opensource = load_json(NORMALIZED_DIR / "opensource.json")
    tech = load_json(NORMALIZED_DIR / "tech.json")
    history = load_json(NORMALIZED_DIR / "history.json")

    security_summary = (security or {}).get("summary", {})
    releases_summary = (releases or {}).get("summary", {})
    opensource_summary = (opensource or {}).get("summary", {})
    tech_summary = (tech or {}).get("summary", {})

    severity = security_summary.get("severity", {})

    # Deterministic generatedAt: newest processedAt across all inputs.
    stamps = []
    for dataset in (security, releases, opensource, tech, history):
        stamp = parse_iso_datetime((dataset or {}).get("meta", {}).get("processedAt"))
        if stamp:
            stamps.append(stamp)
    generated_at = max(stamps).isoformat() if stamps else (
        datetime.strptime(snapshot_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
    )

    history_list = (history or {}).get("history", [])

    def sources_of(dataset: dict[str, Any] | None) -> dict[str, Any]:
        return (dataset or {}).get("meta", {}).get("sources", {})

    return {
        "meta": {
            "date": snapshot_date,
            "generatedAt": generated_at,
            "daysObserved": len(history_list),
            "snapshots": len(history_list),
        },
        "snapshot": {
            "cves": security_summary.get("total", 0),
            "knownExploited": security_summary.get("knownExploited", 0),
            "kevAdded": security_summary.get("kevAddedInWindow", 0),
            "releases": releases_summary.get("total", 0),
            "projects": opensource_summary.get("totalTracked", 0),
            "techEntries": tech_summary.get("total", 0),
        },
        "security": {
            "critical": severity.get("CRITICAL", 0),
            "high": severity.get("HIGH", 0),
            "medium": severity.get("MEDIUM", 0),
            "low": severity.get("LOW", 0),
            "none": severity.get("NONE", 0),
            "unscored": severity.get("UNSCORED", 0),
            "kevCatalogTotal": security_summary.get("kevCatalogTotal", 0),
            "latest": [format_cve(c) for c in (security or {}).get("latest", [])[:15]],
        },
        "releases": [format_release(r) for r in (releases or {}).get("releases", [])[:30]],
        "openSource": [format_project(p) for p in (opensource or {}).get("topProjects", [])[:12]],
        "technology": [format_tech_entry(e) for e in (tech or {}).get("entries", [])[:15]],
        "history": history_list,
        "sources": {
            "security": sources_of(security),
            "releases": sources_of(releases),
            "opensource": sources_of(opensource),
            "technology": sources_of(tech),
        },
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Generate the frontend site data.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD, UTC).")
    args = parser.parse_args()

    snapshot_date = resolve_snapshot_date(args.date)

    print()
    print("TechPulse — Site Data Generator")
    print("=" * 32)
    print(f"Snapshot date: {snapshot_date}")
    print()

    try:
        data = generate_site_data(snapshot_date)
        output_path = GENERATED_DIR / "data.json"
        save_json(data, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Generation completed.")
    print(f"Snapshot : {data['meta']['date']}")
    print(f"CVEs     : {data['snapshot']['cves']}")
    print(f"Releases : {data['snapshot']['releases']}")
    print(f"Projects : {data['snapshot']['projects']}")
    print(f"Output   : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
