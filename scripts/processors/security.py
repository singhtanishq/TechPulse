#!/usr/bin/env python3

"""
TechPulse — Security Processor

Processes NVD and CISA KEV data into normalized security intelligence.
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
    deduplicate_by_key,
    sort_by_severity,
    PROJECT_ROOT,
    DATA_DIR,
)

NVD_DIR = DATA_DIR / "security" / "nvd"
CISA_DIR = DATA_DIR / "security" / "cisa"
NORMALIZED_DIR = DATA_DIR / "normalized"


def load_latest_nvd() -> dict[str, Any] | None:
    """Load the most recent NVD data file."""
    files = list(NVD_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def load_latest_cisa() -> dict[str, Any] | None:
    """Load the most recent CISA KEV data file."""
    files = list(CISA_DIR.glob("*.json"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return load_json(latest)


def get_cisa_kev_ids(cisa_data: dict[str, Any] | None) -> set[str]:
    """Extract CVE IDs from CISA KEV data."""
    if not cisa_data:
        return set()
    return {v.get("cve_id") for v in cisa_data.get("vulnerabilities", []) if v.get("cve_id")}


def enrich_with_kev_status(nvd_vulns: list[dict], kev_ids: set[str]) -> list[dict]:
    """Add known_exploited flag to NVD vulnerabilities."""
    for vuln in nvd_vulns:
        vuln["known_exploited"] = vuln.get("id") in kev_ids
    return nvd_vulns


def filter_by_window(vulns: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Filter vulnerabilities by lastModified date within window."""
    filtered = []
    for vuln in vulns:
        mod_str = vuln.get("lastModified")
        mod_date = parse_iso_datetime(mod_str)
        if mod_date and start <= mod_date <= end:
            filtered.append(vuln)
    return filtered


def get_severity_counts(vulns: list[dict]) -> dict[str, int]:
    """Count vulnerabilities by severity."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0, "UNKNOWN": 0}
    for vuln in vulns:
        sev = vuln.get("severity")
        if sev in counts:
            counts[sev] += 1
        elif sev is None:
            counts["UNKNOWN"] += 1
        else:
            counts["UNKNOWN"] += 1
    return counts


def get_latest_vulnerabilities(vulns: list[dict], limit: int = 10) -> list[dict]:
    """Get latest vulnerabilities sorted by lastModified descending."""
    vulns_with_date = []
    for v in vulns:
        mod_date = parse_iso_datetime(v.get("lastModified"))
        if mod_date:
            vulns_with_date.append((mod_date, v))

    vulns_with_date.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in vulns_with_date[:limit]]


def process_security(
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Process security data from NVD and CISA."""

    print("Loading NVD data...")
    nvd_data = load_latest_nvd()
    if not nvd_data:
        print("WARNING: No NVD data found")
        nvd_vulns = []
    else:
        nvd_vulns = nvd_data.get("vulnerabilities", [])
        print(f"  Loaded {len(nvd_vulns)} NVD vulnerabilities")

    print("Loading CISA KEV data...")
    cisa_data = load_latest_cisa()
    if not cisa_data:
        print("WARNING: No CISA KEV data found")
        kev_ids = set()
    else:
        kev_ids = get_cisa_kev_ids(cisa_data)
        print(f"  Loaded {len(kev_ids)} KEV entries")

    # Enrich NVD with KEV status
    nvd_vulns = enrich_with_kev_status(nvd_vulns, kev_ids)

    # Determine window
    if window_end is None:
        window_end = utc_now()
    if window_start is None:
        window_start = window_end - timedelta(days=1)

    # Filter by window
    window_vulns = filter_by_window(nvd_vulns, window_start, window_end)
    print(f"  {len(window_vulns)} vulnerabilities in window")

    # Severity counts
    severity_counts = get_severity_counts(window_vulns)

    # KEV in window
    kev_in_window = [v for v in window_vulns if v.get("known_exploited")]
    print(f"  {len(kev_in_window)} known exploited in window")

    # Latest vulnerabilities
    latest_vulns = get_latest_vulnerabilities(window_vulns, 10)

    # Build output
    output = {
        "meta": {
            "processedAt": utc_now().isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "sources": {
                "nvd": {
                    "status": "success" if nvd_data else "missing",
                    "total": len(nvd_vulns),
                    "inWindow": len(window_vulns),
                },
                "cisa": {
                    "status": "success" if cisa_data else "missing",
                    "total": len(kev_ids),
                    "inWindow": len(kev_in_window),
                },
            },
        },
        "summary": {
            "total": len(window_vulns),
            "severity": severity_counts,
            "knownExploited": len(kev_in_window),
        },
        "latest": latest_vulns,
    }

    return output


def main() -> int:
    """Main entry point for security processor."""
    parser = __import__("argparse").ArgumentParser(description="Process security data.")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC)")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC)")
    args = parser.parse_args()

    window_start = parse_iso_datetime(args.start) if args.start else None
    window_end = parse_iso_datetime(args.end) if args.end else None

    print()
    print("TechPulse — Security Processor")
    print("=" * 32)
    print()

    try:
        result = process_security(window_start, window_end)
        output_path = NORMALIZED_DIR / "security.json"
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