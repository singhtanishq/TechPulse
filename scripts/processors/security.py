#!/usr/bin/env python3

"""
TechPulse — Security Processor

Normalizes NVD CVE records and the CISA KEV catalog into the
application-ready security dataset.

Semantics preserved:
    - An NVD record without a CVSS score is valid and keeps
      severity=null / cvss=null. Severity is never invented.
    - CISA KEV "known exploited" status is tracked separately from
      NVD severity; the two concepts are never merged.

Output:
    data/normalized/security.json
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
    parse_iso_datetime,
    save_json,
    derive_processed_at,
    status_from_counts,
    utc_now,
)

NVD_DIR = DATA_DIR / "security" / "nvd"
CISA_DIR = DATA_DIR / "security" / "cisa"
NORMALIZED_DIR = DATA_DIR / "normalized"

SEVERITY_KEYS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]


def resolve_window(start_arg: str | None, end_arg: str | None) -> tuple[datetime, datetime]:
    """Resolve the processing window, defaulting to the previous UTC day."""
    end = parse_iso_datetime(end_arg) if end_arg else None
    start = parse_iso_datetime(start_arg) if start_arg else None

    if end is None:
        day = (utc_now() - timedelta(days=1)).date()
        end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1) - timedelta(milliseconds=1)
    if start is None:
        start = end - timedelta(days=1) + timedelta(milliseconds=1)

    return start, end


def severity_counts(vulns: list[dict[str, Any]]) -> dict[str, int]:
    """Count vulnerabilities by severity, including unscored records."""
    counts = {key: 0 for key in SEVERITY_KEYS}
    counts["UNSCORED"] = 0
    for vuln in vulns:
        severity = vuln.get("severity")
        if severity in counts:
            counts[severity] += 1
        else:
            counts["UNSCORED"] += 1
    return counts


def in_window(vuln: dict[str, Any], start: datetime, end: datetime,
              date_field: str = "lastModified") -> bool:
    """Check whether a record's date field falls within the window."""
    stamp = parse_iso_datetime(vuln.get(date_field))
    return stamp is not None and start <= stamp <= end


def latest_by_modified(vulns: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Return the most recently modified vulnerabilities (deterministic)."""
    def sort_key(v: dict[str, Any]):
        stamp = parse_iso_datetime(v.get("lastModified"))
        return (stamp or datetime.min.replace(tzinfo=timezone.utc), v.get("id") or "")

    return sorted(vulns, key=sort_key, reverse=True)[:limit]


def process_security(start: datetime, end: datetime) -> dict[str, Any]:
    """Process security data from NVD and CISA KEV."""

    nvd_path = latest_dated_file(NVD_DIR)
    cisa_path = latest_dated_file(CISA_DIR)

    print("Loading NVD data...")
    nvd_data = load_json(nvd_path) if nvd_path else None
    if not nvd_data:
        print("  WARNING: no NVD data available")
        nvd_vulns: list[dict[str, Any]] = []
        nvd_failures = 1
    else:
        nvd_vulns = [v for v in nvd_data.get("vulnerabilities", []) if isinstance(v, dict)]
        print(f"  Loaded {len(nvd_vulns)} NVD records from {nvd_path.name}")

    print("Loading CISA KEV data...")
    cisa_data = load_json(cisa_path) if cisa_path else None
    if not cisa_data:
        print("  WARNING: no CISA KEV data available")
        kev_records: list[dict[str, Any]] = []
        cisa_failures = 1
    else:
        kev_records = [v for v in cisa_data.get("vulnerabilities", []) if isinstance(v, dict)]
        print(f"  Loaded {len(kev_records)} KEV records from {cisa_path.name}")

    kev_ids = {v.get("cve_id") for v in kev_records if v.get("cve_id")}

    # Enrich NVD records with KEV status.
    for vuln in nvd_vulns:
        vuln["known_exploited"] = vuln.get("id") in kev_ids

    # Window filtering.
    window_vulns = [v for v in nvd_vulns if in_window(v, start, end)]
    kev_in_window = sorted(
        (v for v in kev_records if in_window(v, start, end, "date_added")),
        key=lambda v: (v.get("date_added") or "", v.get("cve_id") or ""),
        reverse=True,
    )

    nvd_failures = 0 if nvd_data else 1
    cisa_failures = 0 if cisa_data else 1

    counts = severity_counts(window_vulns)

    nvd_status = status_from_counts(len(nvd_vulns), len(window_vulns), nvd_failures)
    cisa_status = status_from_counts(len(kev_records), len(kev_in_window), cisa_failures)

    processed_at = derive_processed_at([nvd_path, cisa_path])

    return {
        "meta": {
            "processedAt": processed_at,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "sourceFiles": {
                "nvd": nvd_path.name if nvd_path else None,
                "cisa": cisa_path.name if cisa_path else None,
            },
            "sources": {
                "nvd": {
                    "status": nvd_status,
                    "total": len(nvd_vulns),
                    "inWindow": len(window_vulns),
                    "failures": nvd_failures,
                },
                "cisa": {
                    "status": cisa_status,
                    "total": len(kev_records),
                    "inWindow": len(kev_in_window),
                    "failures": cisa_failures,
                },
            },
        },
        "summary": {
            "total": len(window_vulns),
            "severity": counts,
            "knownExploited": sum(1 for v in window_vulns if v.get("known_exploited")),
            "kevCatalogTotal": len(kev_records),
            "kevAddedInWindow": len(kev_in_window),
        },
        "latest": latest_by_modified(window_vulns, 20),
        "kevRecent": kev_in_window[:10],
    }


def main() -> int:

    parser = argparse.ArgumentParser(description="Process security data (NVD + CISA KEV).")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD, UTC).")
    parser.add_argument("--start", help="Window start (ISO 8601 UTC). Overrides --date.")
    parser.add_argument("--end", help="Window end (ISO 8601 UTC). Overrides --date.")
    args = parser.parse_args()

    if args.start and args.end:
        start = parse_iso_datetime(args.start)
        end = parse_iso_datetime(args.end)
        if start is None or end is None:
            parser.error("Invalid --start/--end datetime.")
    else:
        if args.date:
            try:
                day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                parser.error("--date must be in YYYY-MM-DD format.")
        else:
            day = (utc_now() - timedelta(days=1)).date()
            day = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        start = day
        end = day + timedelta(days=1) - timedelta(milliseconds=1)

    print()
    print("TechPulse — Security Processor")
    print("=" * 32)
    print(f"Window: {start.isoformat()} -> {end.isoformat()}")
    print()

    try:
        result = process_security(start, end)
        output_path = NORMALIZED_DIR / "security.json"
        save_json(result, output_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = result["summary"]
    print()
    print("Processing completed.")
    print(f"In window        : {summary['total']} CVEs")
    print(f"Known exploited  : {summary['knownExploited']} (KEV added: {summary['kevAddedInWindow']})")
    print(f"Output: {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
