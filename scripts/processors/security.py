#!/usr/bin/env python3

"""
TechPulse — Security Processor

Normalizes NVD CVE records and the CISA KEV catalog into the
application-ready security dataset.

Semantics:
    - An NVD record without a CVSS score is valid and keeps
      severity=null / cvss=null. Severity is never invented.
    - CISA KEV "known exploited" status is tracked separately from
      NVD severity; the two concepts are never merged.
    - A source file is valid only when the exact reporting-date file
      exists and contains the expected top-level record list.
    - A missing or malformed source is reported as FAILED.
    - A healthy source containing zero records is reported as EMPTY.
    - A partially collected source is reported as PARTIAL when its
      collector metadata contains failures.

Reporting window:
    The edition for reporting date X (an India calendar day) covers
    the previous IST day [X-1 00:00 IST, X 00:00 IST).

    NVD CVEs are matched by their lastModified instant against this
    half-open window.

    KEV additions are matched by the dateAdded calendar day.

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

from processors.utils import (  # noqa: E402
    DATA_DIR,
    dated_file_for,
    derive_processed_at,
    in_ist_day,
    ist_day_window,
    ist_date_of,
    ist_today,
    load_json,
    parse_ist_date,
    parse_iso_datetime,
    save_json,
    status_from_counts,
)

NVD_DIR = DATA_DIR / "security" / "nvd"
CISA_DIR = DATA_DIR / "security" / "cisa"
NORMALIZED_DIR = DATA_DIR / "normalized"

SEVERITY_KEYS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]


# ------------------------------------------------------------------ #
# Window resolution
# ------------------------------------------------------------------ #

def resolve_window(
    date_arg: str | None,
    start_arg: str | None,
    end_arg: str | None,
) -> tuple[datetime, datetime, str, str]:
    """
    Resolve:

        (window_start, window_end, covered_ist_day, reporting_date)

    Normal mode:
        --date X
        -> window = previous IST calendar day
        -> reporting_date = X

    Explicit window mode:
        --start + --end
        -> window is used exactly as supplied
        -> covered day comes from window start in IST
        -> reporting date is derived from window end in IST unless
           an explicit --date was also supplied.

    Deriving the reporting date here is important because source
    processing must always use an exact date-specific raw file.
    """

    if start_arg or end_arg:
        if not start_arg or not end_arg:
            raise ValueError(
                "--start and --end must be supplied together."
            )

        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)

        if start is None or end is None:
            raise ValueError(
                "Invalid --start/--end datetime."
            )

        if start >= end:
            raise ValueError(
                "--start must be earlier than --end."
            )

        covered_ist_day = ist_date_of(start)

        if date_arg:
            try:
                parse_ist_date(date_arg)
            except ValueError:
                raise ValueError(
                    f"Reporting date must be YYYY-MM-DD (got '{date_arg}')."
                )
            reporting_date = date_arg
        else:
            # The edition starts at the window end, so the IST calendar
            # date of the end instant is the logical reporting date.
            reporting_date = ist_date_of(end)

        return (
            start,
            end,
            covered_ist_day,
            reporting_date,
        )

    reporting_date = date_arg or ist_today()

    try:
        parse_ist_date(reporting_date)
    except ValueError:
        raise ValueError(
            f"Reporting date must be YYYY-MM-DD (got '{reporting_date}')."
        )

    start, end = ist_day_window(reporting_date)

    return (
        start,
        end,
        ist_date_of(start),
        reporting_date,
    )


# ------------------------------------------------------------------ #
# Validation helpers
# ------------------------------------------------------------------ #

def _record_list(
    data: dict[str, Any] | None,
    key: str,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Return (records, structurally_valid).

    A source JSON document is structurally valid only when the expected
    top-level key exists and contains a list.

    This prevents a malformed-but-parseable JSON document such as:
        {"meta": {...}}
    from being mistaken for a healthy empty source.
    """
    if not isinstance(data, dict):
        return [], False

    records = data.get(key)

    if not isinstance(records, list):
        return [], False

    valid_records = [
        record
        for record in records
        if isinstance(record, dict)
    ]

    return valid_records, True


def _collector_failure_count(
    data: dict[str, Any] | None,
) -> int:
    """
    Extract collector-level failures from source metadata.

    Collectors currently store failures as a list in:
        meta.failures

    Be defensive about legacy or malformed metadata.
    """
    if not isinstance(data, dict):
        return 0

    meta = data.get("meta") or {}
    failures = meta.get("failures", [])

    if isinstance(failures, list):
        return len(failures)

    if isinstance(failures, int):
        return max(failures, 0)

    return 0


def _load_source(
    path: Path | None,
    records_key: str,
    source_name: str,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    int,
    str,
]:
    """
    Load one exact-date source and determine its health.

    Returns:
        (data, records, failures, status)

    Status:
        failed  -> exact file missing, unreadable, malformed, or wrong shape
        partial -> source contains data but collector reports failures
        empty   -> source is healthy and contains zero records
        success -> source is healthy and contains records

    IMPORTANT:
        There is intentionally no fallback to another date here.
    """

    print(f"Loading {source_name} data...")

    if path is None:
        print(
            f"  FAILED: exact {source_name} source file is missing"
        )
        return None, [], 1, "failed"

    data = load_json(path)

    if data is None:
        print(
            f"  FAILED: {source_name} source file is unreadable or invalid JSON: "
            f"{path.name}"
        )
        return None, [], 1, "failed"

    records, structurally_valid = _record_list(
        data,
        records_key,
    )

    if not structurally_valid:
        print(
            f"  FAILED: {source_name} source file is missing expected "
            f"'{records_key}' list: {path.name}"
        )
        return data, [], 1, "failed"

    collector_failures = _collector_failure_count(data)

    if collector_failures > 0:
        status = "partial" if records else "failed"
    elif not records:
        status = "empty"
    else:
        status = "success"

    print(
        f"  Loaded {len(records)} records from {path.name} "
        f"(status={status})"
    )

    if collector_failures:
        print(
            f"  Collector failures reported: {collector_failures}"
        )

    # If the collector explicitly says failures occurred but no records
    # survived, this is a failed source rather than a healthy empty one.
    if collector_failures > 0 and not records:
        status = "failed"

    return (
        data,
        records,
        collector_failures,
        status,
    )


# ------------------------------------------------------------------ #
# Security-specific processing
# ------------------------------------------------------------------ #

def severity_counts(
    vulns: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Count vulnerabilities by severity, including unscored records.
    """
    counts = {
        key: 0
        for key in SEVERITY_KEYS
    }
    counts["UNSCORED"] = 0

    for vuln in vulns:
        severity = vuln.get("severity")

        if severity in counts:
            counts[severity] += 1
        else:
            counts["UNSCORED"] += 1

    return counts


def in_window(
    vuln: dict[str, Any],
    start: datetime,
    end: datetime,
    date_field: str = "lastModified",
) -> bool:
    """
    Check whether a record's date field falls within [start, end).
    """
    stamp = parse_iso_datetime(
        vuln.get(date_field)
    )

    return (
        stamp is not None
        and start <= stamp < end
    )


def latest_by_modified(
    vulns: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """
    Return the most recently modified vulnerabilities deterministically.
    """

    def sort_key(vuln: dict[str, Any]):
        stamp = parse_iso_datetime(
            vuln.get("lastModified")
        )

        if stamp is None:
            stamp = datetime.min.replace(
                tzinfo=timezone.utc
            )

        return (
            stamp,
            vuln.get("id") or "",
        )

    return sorted(
        vulns,
        key=sort_key,
        reverse=True,
    )[:limit]


def process_security(
    start: datetime,
    end: datetime,
    covered_ist_day: str,
    reporting_date: str | None = None,
) -> dict[str, Any]:
    """
    Process NVD and CISA KEV source data.

    DATE ISOLATION:
        When processing an edition, the exact reporting-date source file
        must exist. No older or newer source file is substituted.

    When reporting_date is omitted by a direct caller, it is derived
    from the supplied covered IST day. This keeps explicit test and
    utility calls date-safe as well.
    """

    if reporting_date is None:
        reporting_date = (
            parse_ist_date(covered_ist_day)
            + timedelta(days=1)
        ).isoformat()

    # Validate both dates before constructing paths.
    try:
        parse_ist_date(covered_ist_day)
        parse_ist_date(reporting_date)
    except ValueError as exc:
        raise ValueError(
            f"Invalid security processing date: {exc}"
        ) from exc

    nvd_path = dated_file_for(
        NVD_DIR,
        reporting_date,
    )
    cisa_path = dated_file_for(
        CISA_DIR,
        reporting_date,
    )

    (
        nvd_data,
        nvd_vulns,
        nvd_failures,
        nvd_status,
    ) = _load_source(
        nvd_path,
        "vulnerabilities",
        "NVD",
    )

    (
        cisa_data,
        kev_records,
        cisa_failures,
        cisa_status,
    ) = _load_source(
        cisa_path,
        "vulnerabilities",
        "CISA KEV",
    )

    # Build the current KEV ID set from the exact same reporting-date
    # CISA snapshot used for this edition.
    kev_ids = {
        vuln.get("cve_id")
        for vuln in kev_records
        if vuln.get("cve_id")
    }

    # Enrich NVD records with KEV status.
    #
    # This is intentionally separate from NVD severity. A CVE can be:
    #   - high severity but not in KEV
    #   - low severity and in KEV
    #   - unscored and in KEV
    for vuln in nvd_vulns:
        vuln["known_exploited"] = (
            vuln.get("id") in kev_ids
        )

    # -------------------------------------------------------------- #
    # Window filtering
    # -------------------------------------------------------------- #

    # NVD records are matched by their lastModified instant.
    window_vulns = [
        vuln
        for vuln in nvd_vulns
        if in_window(
            vuln,
            start,
            end,
        )
    ]

    # KEV additions are matched by the dateAdded IST calendar day.
    kev_in_window = sorted(
        (
            vuln
            for vuln in kev_records
            if in_ist_day(
                vuln.get("date_added"),
                covered_ist_day,
            )
        ),
        key=lambda vuln: (
            vuln.get("date_added") or "",
            vuln.get("cve_id") or "",
        ),
        reverse=True,
    )

    counts = severity_counts(
        window_vulns
    )

    # Use actual source health where available. status_from_counts is
    # retained as a defensive fallback for the final semantics.
    if nvd_status == "failed":
        final_nvd_status = "failed"
    elif nvd_status == "partial":
        final_nvd_status = "partial"
    elif not window_vulns:
        final_nvd_status = "empty"
    else:
        final_nvd_status = "success"

    if cisa_status == "failed":
        final_cisa_status = "failed"
    elif cisa_status == "partial":
        final_cisa_status = "partial"
    elif not kev_in_window:
        # A full healthy KEV catalog with no additions on the covered
        # day is a legitimate empty daily delta.
        final_cisa_status = "empty"
    else:
        final_cisa_status = "success"

    # Defensive consistency checks: these should not normally change the
    # statuses above, but preserve the documented generic semantics.
    if final_nvd_status == "success":
        final_nvd_status = status_from_counts(
            len(nvd_vulns),
            len(window_vulns),
            nvd_failures,
        )

    if final_cisa_status == "success":
        final_cisa_status = status_from_counts(
            len(kev_records),
            len(kev_in_window),
            cisa_failures,
        )

    processed_at = derive_processed_at(
        [
            nvd_path,
            cisa_path,
        ]
    )

    return {
        "meta": {
            "processedAt": processed_at,
            "reportingDate": reporting_date,
            "coveredIstDay": covered_ist_day,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "sourceFiles": {
                "nvd": nvd_path.name if nvd_path else None,
                "cisa": cisa_path.name if cisa_path else None,
            },
            "sources": {
                "nvd": {
                    "status": final_nvd_status,
                    "total": len(nvd_vulns),
                    "inWindow": len(window_vulns),
                    "failures": nvd_failures,
                },
                "cisa": {
                    "status": final_cisa_status,
                    "total": len(kev_records),
                    "inWindow": len(kev_in_window),
                    "failures": cisa_failures,
                },
            },
        },
        "summary": {
            "total": len(window_vulns),
            "severity": counts,
            "knownExploited": sum(
                1
                for vuln in window_vulns
                if vuln.get("known_exploited")
            ),
            "kevCatalogTotal": len(kev_records),
            "kevAddedInWindow": len(kev_in_window),
        },
        "latest": latest_by_modified(
            window_vulns,
            20,
        ),
        "kevRecent": kev_in_window[:10],
    }


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Process security data (NVD + CISA KEV)."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date (YYYY-MM-DD, IST edition)."
        ),
    )

    parser.add_argument(
        "--start",
        help=(
            "Window start (ISO 8601). Overrides --date."
        ),
    )

    parser.add_argument(
        "--end",
        help=(
            "Window end (ISO 8601, exclusive). Overrides --date."
        ),
    )

    args = parser.parse_args()

    print()
    print("TechPulse — Security Processor")
    print("=" * 32)

    try:
        (
            start,
            end,
            covered_ist_day,
            reporting_date,
        ) = resolve_window(
            args.date,
            args.start,
            args.end,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        f"Reporting date: {reporting_date}"
    )
    print(
        f"Covered IST day: {covered_ist_day}"
    )
    print(
        f"Window: {start.isoformat()} -> "
        f"{end.isoformat()} (end exclusive)"
    )
    print()

    try:
        result = process_security(
            start,
            end,
            covered_ist_day,
            reporting_date,
        )

        output_path = (
            NORMALIZED_DIR
            / "security.json"
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

    summary = result["summary"]
    sources = result["meta"]["sources"]

    print()
    print("Processing completed.")
    print(
        f"In window        : {summary['total']} CVEs"
    )
    print(
        f"Known exploited  : "
        f"{summary['knownExploited']} "
        f"(KEV added: {summary['kevAddedInWindow']})"
    )
    print(
        f"NVD status       : "
        f"{sources['nvd']['status']}"
    )
    print(
        f"CISA KEV status  : "
        f"{sources['cisa']['status']}"
    )
    print(
        f"Output            : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
