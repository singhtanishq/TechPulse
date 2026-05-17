#!/usr/bin/env python3

"""
TechPulse — Site Data Generator

Generates the main frontend data file from normalized processor outputs.
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
    format_date,
    format_relative_date,
    PROJECT_ROOT,
    DATA_DIR,
)

NORMALIZED_DIR = DATA_DIR / "normalized"
GENERATED_DIR = PROJECT_ROOT / "generated"


def load_normalized(name: str) -> dict[str, Any] | None:
    """Load a normalized data file."""
    path = NORMALIZED_DIR / f"{name}.json"
    return load_json(path)


def format_cve_for_frontend(cve: dict) -> dict:
    """Format a CVE for frontend display."""
    return {
        "id": cve.get("id", ""),
        "title": cve.get("description", "")[:120] + ("..." if len(cve.get("description", "")) > 120 else ""),
        "severity": cve.get("severity", "UNKNOWN"),
        "cvss_score": cve.get("cvss", {}).get("score") if cve.get("cvss") else None,
        "cvss_version": cve.get("cvss", {}).get("version") if cve.get("cvss") else None,
        "published": format_relative_date(cve.get("published")),
        "modified": format_relative_date(cve.get("lastModified")),
        "known_exploited": cve.get("known_exploited", False),
        "url": f"https://nvd.nist.gov/vuln/detail/{cve.get('id')}" if cve.get("id") else "",
    }


def format_release_for_frontend(rel: dict) -> dict:
    """Format a release for frontend display."""
    return {
        "project": rel.get("project", ""),
        "repository": rel.get("repository", ""),
        "version": rel.get("version", ""),
        "date": format_relative_date(rel.get("published_at")),
        "url": rel.get("url", ""),
    }


def format_project_for_frontend(proj: dict) -> dict:
    """Format a project for frontend display."""
    return {
        "rank": proj.get("rank", 0),
        "name": proj.get("name", ""),
        "full_name": proj.get("full_name", ""),
        "description": proj.get("description", ""),
        "stars": proj.get("stars", 0),
        "daily_growth": proj.get("daily_growth"),
        "url": proj.get("url", ""),
        "language": proj.get("language", ""),
    }


def format_tech_entry_for_frontend(entry: dict) -> dict:
    """Format a tech entry for frontend display."""
    return {
        "title": entry.get("title", ""),
        "url": entry.get("url", ""),
        "source": entry.get("feed_source", ""),
        "category": entry.get("feed_category", "tech"),
        "date": format_relative_date(entry.get("published_at")),
        "summary": entry.get("summary_short", entry.get("summary", "")),
    }


def generate_site_data() -> dict[str, Any]:
    """Generate the complete site data for frontend."""

    print("Loading normalized data...")
    security = load_normalized("security")
    releases = load_normalized("releases")
    opensource = load_normalized("opensource")
    tech = load_normalized("tech")
    history = load_normalized("history")

    # Current date for display
    today = utc_now()

    # Security data
    security_summary = security.get("summary", {}) if security else {}
    security_latest = security.get("latest", []) if security else []

    # Releases data
    releases_summary = releases.get("summary", {}) if releases else {}
    releases_list = releases.get("releases", []) if releases else []

    # Open source data
    opensource_summary = opensource.get("summary", {}) if opensource else {}
    top_projects = opensource.get("topProjects", []) if opensource else []

    # Tech data
    tech_summary = tech.get("summary", {}) if tech else {}
    tech_entries = tech.get("entries", []) if tech else []

    # History
    history_list = history.get("history", []) if history else []

    # Build site data matching frontend expectations
    site_data = {
        "meta": {
            "date": today.date().isoformat(),
            "generatedAt": utc_now().isoformat(),
            "daysObserved": len(history_list),
            "snapshots": len(history_list),
        },
        "snapshot": {
            "cves": security_summary.get("total", 0),
            "knownExploited": security_summary.get("knownExploited", 0),
            "releases": releases_summary.get("total", 0),
            "projects": opensource_summary.get("totalTracked", 0),
            "techEntries": tech_summary.get("total", 0),
        },
        "security": {
            "critical": security_summary.get("severity", {}).get("CRITICAL", 0),
            "high": security_summary.get("severity", {}).get("HIGH", 0),
            "medium": security_summary.get("severity", {}).get("MEDIUM", 0),
            "low": security_summary.get("severity", {}).get("LOW", 0),
            "unknown": security_summary.get("severity", {}).get("UNKNOWN", 0),
            "latest": [format_cve_for_frontend(c) for c in security_latest[:10]],
        },
        "releases": [format_release_for_frontend(r) for r in releases_list[:20]],
        "openSource": [format_project_for_frontend(p) for p in top_projects[:10]],
        "technology": [format_tech_entry_for_frontend(e) for e in tech_entries[:10]],
        "history": history_list,
        "sources": {
            "security": security.get("meta", {}).get("sources", {}) if security else {},
            "releases": releases.get("meta", {}).get("sources", {}) if releases else {},
            "opensource": opensource.get("meta", {}).get("sources", {}) if opensource else {},
            "technology": tech.get("meta", {}).get("sources", {}) if tech else {},
        },
    }

    return site_data


def main() -> int:
    """Main entry point for site data generator."""

    print()
    print("TechPulse — Site Data Generator")
    print("=" * 32)
    print()

    try:
        data = generate_site_data()
        output_path = GENERATED_DIR / "data.json"
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