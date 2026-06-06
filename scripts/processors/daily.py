#!/usr/bin/env python3

"""
TechPulse — Daily Snapshot Processor

Creates the daily snapshot archive record from all normalized datasets.

Semantics:
    A snapshot covers exactly one UTC calendar day. Snapshots are
    append-only: an existing snapshot for a date is never silently
    rewritten unless its content meaningfully changes (record counts
    and statistics). The generation timestamp is derived from source
    data so reprocessing identical inputs is a no-op.

Output:
    data/daily/YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (
    DATA_DIR,
    NORMALIZED_DIR,
    load_json,
    save_json,
    parse_iso_datetime,
    utc_now,
    format_relative_date,
)

DAILY_DIR = DATA_DIR / "daily"


def resolve_snapshot_date(date_arg: str | None) -> datetime:
    if date_arg:
        try:
            return datetime.strptime(date_arg, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise SystemExit("--date must be in YYYY-MM-DD format.")
    day = (utc_now() - timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def resolve_window(date_arg: str | None, start_arg: str | None, end_arg: str | None):
    if start_arg and end_arg:
        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)
        if start is None or end is None:
            raise SystemExit("Invalid --start/--end datetime.")
        return start, end
    day = resolve_snapshot_date(date_arg)
    return day, day + timedelta(days=1) - timedelta(milliseconds=1)


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    """Fingerprint of snapshot content excluding volatile fields."""
    content = {k: v for k, v in snapshot.items() if k != "generatedAt"}
    return json.dumps(content, sort_keys=True, ensure_ascii=False)


def process_daily(
    snapshot_date: datetime,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Create the daily snapshot from normalized datasets."""

    print(f"Creating daily snapshot for {snapshot_date.date().isoformat()}...")

    security = load_json(NORMALIZED_DIR / "security.json")
    releases = load_json(NORMALIZED_DIR / "releases.json")
    opensource = load_json(NORMALIZED_DIR / "opensource.json")
    tech = load_json(NORMALIZED_DIR / "tech.json")

    security_summary = (security or {}).get("summary", {})
    releases_summary = (releases or {}).get("summary", {})
    opensource_summary = (opensource or {}).get("summary", {})
    tech_summary = (tech or {}).get("summary", {})

    def source_block(dataset: dict[str, Any] | None, name: str) -> dict[str, Any]:
        sources = (dataset or {}).get("meta", {}).get("sources", {})
        return sources.get(name, {"status": "missing", "total": 0, "inWindow": 0, "failures": 0})

    sources = {
        "nvd": source_block(security, "nvd"),
        "cisa": source_block(security, "cisa"),
        "github_releases": source_block(releases, "github"),
        "github_repos": source_block(opensource, "github"),
        "rss": source_block(tech, "rss"),
    }

    # Deterministic generation timestamp: newest processedAt across inputs.
    stamps = []
    for dataset in (security, releases, opensource, tech):
        stamp = parse_iso_datetime((dataset or {}).get("meta", {}).get("processedAt"))
        if stamp:
            stamps.append(stamp)
    generated_at = max(stamps).isoformat() if stamps else snapshot_date.isoformat()

    # Severity for the record.
    severity = security_summary.get("severity", {})

    latest_vulns = (security or {}).get("latest", [])[:10]
    kev_recent = (security or {}).get("kevRecent", [])[:5]
    recent_releases = (releases or {}).get("releases", [])[:10]
    top_projects = (opensource or {}).get("topProjects", [])[:10]
    recent_entries = (tech or {}).get("entries", [])[:10]

    def brief_vuln(v: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": v.get("id"),
            "severity": v.get("severity"),
            "cvss": (v.get("cvss") or {}).get("score") if v.get("cvss") else None,
            "known_exploited": v.get("known_exploited", False),
            "description": (v.get("description") or "")[:200],
            "url": f"https://nvd.nist.gov/vuln/detail/{v.get('id')}" if v.get("id") else None,
        }

    def brief_release(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "project": r.get("project"),
            "repository": r.get("repository"),
            "version": r.get("version"),
            "published_at": r.get("published_at"),
            "url": r.get("url"),
        }

    def brief_project(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "full_name": p.get("full_name"),
            "stars": p.get("stars"),
            "daily_growth": p.get("daily_growth"),
            "language": p.get("language"),
            "url": p.get("url"),
        }

    def brief_entry(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": e.get("title"),
            "url": e.get("url"),
            "source": e.get("feed_source"),
            "published_at": e.get("published_at"),
        }

    snapshot: dict[str, Any] = {
        "date": snapshot_date.date().isoformat(),
        "generatedAt": generated_at,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
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
            "severity": severity,
            "latest": [brief_vuln(v) for v in latest_vulns],
            "kevRecent": [
                {
                    "cve_id": v.get("cve_id"),
                    "vendor_project": v.get("vendor_project"),
                    "product": v.get("product"),
                    "vulnerability_name": v.get("vulnerability_name"),
                    "date_added": v.get("date_added"),
                }
                for v in kev_recent
            ],
        },
        "releases": {
            "categories": releases_summary.get("categories", {}),
            "recent": [brief_release(r) for r in recent_releases],
        },
        "opensource": {
            "growthBasis": opensource_summary.get("growthBasis", "unavailable"),
            "topProjects": [brief_project(p) for p in top_projects],
        },
        "technology": {
            "categories": tech_summary.get("categories", {}),
            "sources": tech_summary.get("sources", {}),
            "recent": [brief_entry(e) for e in recent_entries],
        },
        "sources": sources,
    }

    return snapshot


def save_daily_snapshot(snapshot: dict[str, Any]) -> Path:
    """Save the snapshot append-only: never overwrite changed history silently."""

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DAILY_DIR / f"{snapshot['date']}.json"

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if snapshot_fingerprint(existing) == snapshot_fingerprint(snapshot):
                print(f"Snapshot for {snapshot['date']} unchanged; keeping existing file.")
                return output_path
        except (json.JSONDecodeError, OSError):
            pass

    save_json(snapshot, output_path)
    return output_path


def main() -> int:

    parser = argparse.ArgumentParser(description="Create the daily snapshot.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD, UTC).")
    parser.add_argument("--start", help="Window start override (ISO 8601 UTC).")
    parser.add_argument("--end", help="Window end override (ISO 8601 UTC).")
    args = parser.parse_args()

    snapshot_date = resolve_snapshot_date(args.date)
    window_start, window_end = resolve_window(args.date, args.start, args.end)

    print()
    print("TechPulse — Daily Snapshot Processor")
    print("=" * 32)
    print()

    try:
        snapshot = process_daily(snapshot_date, window_start, window_end)
        output_path = save_daily_snapshot(snapshot)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    counts = snapshot["snapshot"]
    print()
    print("Daily snapshot created.")
    print(f"Date      : {snapshot['date']}")
    print(f"CVEs      : {counts['cves']}")
    print(f"Releases  : {counts['releases']}")
    print(f"Projects  : {counts['projects']}")
    print(f"Tech      : {counts['techEntries']}")
    print(f"Output    : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
