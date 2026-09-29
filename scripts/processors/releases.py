#!/usr/bin/env python3

"""
TechPulse — Releases Processor

Normalizes GitHub release records into the application-ready
releases dataset for the edition's reporting window.

Reporting window:
    The edition for reporting date X (an India calendar day) covers the
    previous IST day [X-1 00:00 IST, X 00:00 IST).

    Releases are matched by their published_at instant against this
    half-open window.

Source integrity:
    - The exact reporting-date raw file must exist.
    - The source file's meta.reportingDate must match the requested
      reporting date when that metadata is available.
    - Another date's raw file is NEVER substituted.
    - Missing, unreadable, malformed, or date-mismatched source data is
      reported as FAILED rather than silently becoming an empty dataset.
    - A healthy source with zero releases in the reporting window is
      reported as EMPTY.
    - Collector-reported failures produce PARTIAL when usable records
      are still available.

Output:
    data/normalized/releases.json
"""

from __future__ import annotations

import argparse
import re
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
    ist_day_window,
    ist_date_of,
    ist_today,
    load_json,
    parse_ist_date,
    parse_iso_datetime,
    save_json,
)

RELEASES_DIR = DATA_DIR / "releases"
NORMALIZED_DIR = DATA_DIR / "normalized"

# Semantic-version core with optional prerelease/build metadata.
#
# Examples accepted:
#   1.2.3
#   v1.2.3
#   1.2.3-beta
#   v2.0.0+build.123
#
# Examples rejected:
#   1.2
#   1.2.3foo
#   release-1.2.3
#
# GitHub prereleases are already excluded by the collector, but allowing
# valid semver prerelease/build syntax here keeps processing robust for
# legacy raw data.
VERSION_RE = re.compile(
    r"^v?"
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


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
        -> previous IST calendar day
        -> reporting date remains X

    Explicit window mode:
        --start + --end
        -> supplied window is used exactly
        -> covered day is derived from window start in IST
        -> reporting date is either the explicit --date or the IST
           calendar date represented by the window end.

    The returned dates are always timezone-aware.
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
            # In the standard model, the reporting edition begins at the
            # end boundary of the covered day.
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
# Source loading + validation
# ------------------------------------------------------------------ #

def _collector_failure_count(
    data: dict[str, Any],
) -> int:
    """
    Extract collector-reported failures from meta.failures.

    Expected current format:
        "failures": [...]

    Legacy integer values are also handled defensively.
    """
    meta = data.get("meta") or {}
    failures = meta.get("failures", [])

    if isinstance(failures, list):
        return len(failures)

    if isinstance(failures, int):
        return max(failures, 0)

    return 0


def _load_release_source(
    path: Path | None,
    reporting_date: str,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    int,
    str,
]:
    """
    Load and validate the exact reporting-date release source.

    Returns:
        (source_data, releases, collector_failures, status)

    Status:
        failed  -> missing/invalid/date-mismatched source
        partial -> usable records plus collector failures
        empty   -> valid source, zero records
        success -> valid source with records
    """

    print("Loading releases data...")

    if path is None:
        print(
            f"  FAILED: exact GitHub releases source file for "
            f"{reporting_date} is missing"
        )
        return None, [], 1, "failed"

    data = load_json(path)

    if data is None:
        print(
            f"  FAILED: releases source is missing, unreadable, or "
            f"invalid JSON: {path.name}"
        )
        return None, [], 1, "failed"

    # The source collector should always identify which reporting date
    # produced the file. If metadata is present and disagrees with the
    # requested edition, reject the source instead of processing it.
    meta = data.get("meta") or {}
    source_reporting_date = meta.get("reportingDate")

    if source_reporting_date is not None:
        if source_reporting_date != reporting_date:
            print(
                f"  FAILED: source file {path.name} declares "
                f"reportingDate={source_reporting_date!r}, expected "
                f"{reporting_date!r}"
            )
            return data, [], 1, "failed"

    releases = data.get("releases")

    if not isinstance(releases, list):
        print(
            f"  FAILED: {path.name} is missing the expected "
            "'releases' list"
        )
        return data, [], 1, "failed"

    valid_releases = [
        release
        for release in releases
        if isinstance(release, dict)
    ]

    invalid_record_count = len(releases) - len(valid_releases)

    collector_failures = _collector_failure_count(data)

    # Invalid list items are a source-quality problem. They should not
    # make an otherwise valid source appear perfectly healthy.
    total_failures = collector_failures

    if invalid_record_count:
        total_failures += invalid_record_count
        print(
            f"  WARNING: ignored {invalid_record_count} malformed "
            f"release record(s)"
        )

    if total_failures > 0 and valid_releases:
        status = "partial"
    elif total_failures > 0:
        status = "failed"
    elif not valid_releases:
        status = "empty"
    else:
        status = "success"

    print(
        f"  Loaded {len(valid_releases)} releases from {path.name} "
        f"(status={status})"
    )

    if collector_failures:
        print(
            f"  Collector failures reported: {collector_failures}"
        )

    return (
        data,
        valid_releases,
        total_failures,
        status,
    )


# ------------------------------------------------------------------ #
# Release classification
# ------------------------------------------------------------------ #

def release_kind(version: str) -> str:
    """
    Classify a semantic version as major / minor / patch / other.

    Rules:
        X.0.0 -> major
        X.Y.0 -> minor
        X.Y.Z -> patch

    A valid semver prerelease/build suffix does not change the core
    classification.

    Anything that is not a valid semantic version is classified as
    "other" rather than being classified from a partial prefix.
    """
    if not isinstance(version, str):
        return "other"

    version = version.strip()

    match = VERSION_RE.fullmatch(version)

    if not match:
        return "other"

    major, minor, patch = (
        int(group)
        for group in match.groups()[:3]
    )

    if minor == 0 and patch == 0:
        return "major"

    if patch == 0:
        return "minor"

    return "patch"


# ------------------------------------------------------------------ #
# Processing
# ------------------------------------------------------------------ #

def process_releases(
    start: datetime,
    end: datetime,
    covered_ist_day: str,
    reporting_date: str | None = None,
) -> dict[str, Any]:
    """
    Process GitHub release data for exactly one TechPulse edition.

    A missing exact-date source produces a FAILED GitHub source state.
    It never falls back to another date's raw file.
    """

    if reporting_date is None:
        reporting_date = (
            parse_ist_date(covered_ist_day)
            + timedelta(days=1)
        ).isoformat()

    try:
        parse_ist_date(reporting_date)
        parse_ist_date(covered_ist_day)
    except ValueError as exc:
        raise ValueError(
            f"Invalid release processing date: {exc}"
        ) from exc

    releases_path = dated_file_for(
        RELEASES_DIR,
        reporting_date,
    )

    (
        releases_data,
        all_releases,
        failures,
        source_status,
    ) = _load_release_source(
        releases_path,
        reporting_date,
    )

    window_releases: list[dict[str, Any]] = []

    for release in all_releases:
        published = parse_iso_datetime(
            release.get("published_at")
        )

        if published is None:
            # An otherwise valid record without a usable publication
            # timestamp cannot be assigned to a reporting window.
            failures += 1
            continue

        if start <= published < end:
            enriched = dict(release)
            enriched["kind"] = release_kind(
                release.get("version", "")
            )

            # Relative dates are deliberately not stored here.
            # The frontend derives them from published_at.
            window_releases.append(enriched)

    # Deterministic ordering:
    #   1. publication timestamp descending
    #   2. repository descending
    #   3. version descending
    window_releases.sort(
        key=lambda release: (
            release.get("published_at") or "",
            release.get("repository") or "",
            release.get("version") or "",
        ),
        reverse=True,
    )

    categories = {
        "major": 0,
        "minor": 0,
        "patch": 0,
        "other": 0,
    }

    for release in window_releases:
        categories[release["kind"]] += 1

    # Recalculate the final source state after window processing.
    #
    # Important:
    # - failure + usable records => partial
    # - failure + no usable records => failed
    # - no failure + no releases in window => empty
    # - no failure + releases in window => success
    if failures > 0:
        final_status = (
            "partial"
            if all_releases
            else "failed"
        )
    elif not window_releases:
        final_status = "empty"
    else:
        final_status = "success"

    # Preserve an explicit structural failure even when a legacy source
    # loader happened to return some records.
    if source_status == "failed" and not all_releases:
        final_status = "failed"

    processed_at = derive_processed_at(
        [releases_path]
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
                "releases": (
                    releases_path.name
                    if releases_path
                    else None
                ),
            },
            "sources": {
                "github": {
                    "status": final_status,
                    "total": len(all_releases),
                    "inWindow": len(window_releases),
                    "failures": failures,
                },
            },
        },
        "summary": {
            "total": len(window_releases),
            "categories": categories,
        },
        "releases": window_releases[:50],
    }


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process GitHub releases data."
    )

    parser.add_argument(
        "--date",
        help="Reporting date (YYYY-MM-DD, IST edition).",
    )

    parser.add_argument(
        "--start",
        help="Window start (ISO 8601). Overrides --date.",
    )

    parser.add_argument(
        "--end",
        help="Window end (ISO 8601, exclusive). Overrides --date.",
    )

    args = parser.parse_args()

    print()
    print("TechPulse — Releases Processor")
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
        result = process_releases(
            start,
            end,
            covered_ist_day,
            reporting_date,
        )

        output_path = (
            NORMALIZED_DIR
            / "releases.json"
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
    github_source = (
        result["meta"]["sources"]["github"]
    )

    print()
    print("Processing completed.")
    print(
        f"In window       : "
        f"{summary['total']} releases"
    )
    print(
        f"Major           : "
        f"{summary['categories']['major']}"
    )
    print(
        f"Minor           : "
        f"{summary['categories']['minor']}"
    )
    print(
        f"Patch           : "
        f"{summary['categories']['patch']}"
    )
    print(
        f"Other           : "
        f"{summary['categories']['other']}"
    )
    print(
        f"GitHub status   : "
        f"{github_source['status']}"
    )
    print(
        f"Output          : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
