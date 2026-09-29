#!/usr/bin/env python3

"""
TechPulse — Daily Snapshot Processor

Creates the daily snapshot archive record from all normalized datasets.

Semantics:
    A snapshot (edition) represents one TechPulse reporting date — an
    India calendar day (Asia/Kolkata).

    The edition for date X covers the previous IST day:
    [X-1 00:00 IST, X 00:00 IST).

    Normalized inputs must belong to the same reporting date as the
    snapshot being created. This prevents historical processing from
    accidentally consuming data from a different edition.

    Snapshot writes are idempotent:
        - identical content -> existing file is preserved
        - changed content -> snapshot is explicitly replaced with the
          newly generated version

Output:
    data/daily/YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    DATA_DIR,
    NORMALIZED_DIR,
    ist_day_window,
    ist_date_of,
    ist_today,
    load_json,
    parse_iso_datetime,
    parse_ist_date,
    save_json,
)

DAILY_DIR = DATA_DIR / "daily"


def _validate_reporting_date(
    value: str,
    field_name: str = "reporting date",
) -> str:
    """Validate a real YYYY-MM-DD reporting date."""
    try:
        parsed = parse_ist_date(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format."
        ) from None

    if parsed is None:
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format."
        )

    return value


def resolve_snapshot_date(
    date_arg: str | None,
    start_arg: str | None = None,
    end_arg: str | None = None,
) -> str:
    """
    Resolve the reporting date for the snapshot.

    Priority:
        explicit --date
        explicit --start/--end -> IST date at the exclusive end
        current IST date

    For the normal edition window, an end boundary of midnight IST
    therefore maps directly to the reporting date of that edition.
    """
    if date_arg:
        return _validate_reporting_date(
            date_arg,
            "--date",
        )

    if start_arg and end_arg:
        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)

        if start is None or end is None:
            raise ValueError(
                "--start/--end must be valid ISO-8601 datetimes."
            )

        if start >= end:
            raise ValueError(
                "--start datetime must be earlier than --end datetime."
            )

        return ist_date_of(end)

    if start_arg or end_arg:
        raise ValueError(
            "--start and --end must be supplied together."
        )

    return ist_today()


def resolve_window(
    reporting_date: str,
    start_arg: str | None,
    end_arg: str | None,
) -> tuple[datetime, datetime]:
    """
    Resolve the snapshot window.

    When an explicit window is supplied it is used exactly as given.

    Otherwise the window is the standard TechPulse IST edition window
    for the supplied reporting date:
        [X-1 00:00 IST, X 00:00 IST)
    """
    if start_arg and end_arg:
        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)

        if start is None or end is None:
            raise ValueError(
                "--start/--end must be valid ISO-8601 datetimes."
            )

        if start >= end:
            raise ValueError(
                "--start datetime must be earlier than --end datetime."
            )

        return start, end

    if start_arg or end_arg:
        raise ValueError(
            "--start and --end must be supplied together."
        )

    _validate_reporting_date(
        reporting_date,
        "reporting date",
    )

    return ist_day_window(reporting_date)


def snapshot_fingerprint(
    snapshot: dict[str, Any],
) -> str:
    """Fingerprint snapshot content excluding volatile fields."""
    content = {
        key: value
        for key, value in snapshot.items()
        if key != "generatedAt"
    }

    return json.dumps(
        content,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _safe_summary(
    dataset: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a dataset summary only when it has the expected shape."""
    if not isinstance(
        dataset,
        dict,
    ):
        return {}

    summary = dataset.get(
        "summary",
        {}
    )

    return (
        summary
        if isinstance(
            summary,
            dict,
        )
        else {}
    )


def _safe_meta(
    dataset: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return dataset metadata only when it has the expected shape."""
    if not isinstance(
        dataset,
        dict,
    ):
        return {}

    meta = dataset.get(
        "meta",
        {}
    )

    return (
        meta
        if isinstance(
            meta,
            dict,
        )
        else {}
    )


def _safe_nonnegative_int(
    value: Any,
    default: int = 0,
) -> int:
    """Normalize a count without turning invalid values into arbitrary data."""
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            int,
        )
        or value < 0
    ):
        return default

    return value


def _source_block(
    dataset: dict[str, Any] | None,
    name: str,
) -> dict[str, Any]:
    """Extract normalized source-health information."""
    meta = _safe_meta(dataset)

    sources = meta.get(
        "sources",
        {}
    )

    if not isinstance(
        sources,
        dict,
    ):
        sources = {}

    source = sources.get(
        name
    )

    if not isinstance(
        source,
        dict,
    ):
        return {
            "status": "unknown",
            "total": 0,
            "inWindow": 0,
            "failures": 0,
        }

    return {
        "status": source.get(
            "status",
            "unknown",
        ),
        "total": _safe_nonnegative_int(
            source.get("total"),
        ),
        "inWindow": _safe_nonnegative_int(
            source.get("inWindow"),
        ),
        "failures": _safe_nonnegative_int(
            source.get("failures"),
        ),
    }


def _validate_normalized_dataset(
    dataset: dict[str, Any] | None,
    dataset_name: str,
    reporting_date: str,
) -> None:
    """
    Prevent normalized data from another reporting date being used
    in the current snapshot.
    """
    if dataset is None:
        return

    if not isinstance(
        dataset,
        dict,
    ):
        raise ValueError(
            f"{dataset_name}: normalized dataset root must be an object."
        )

    meta = _safe_meta(
        dataset
    )

    dataset_date = meta.get(
        "reportingDate"
    )

    if not dataset_date:
        raise ValueError(
            f"{dataset_name}: normalized dataset is missing "
            "meta.reportingDate."
        )

    if not isinstance(
        dataset_date,
        str,
    ):
        raise ValueError(
            f"{dataset_name}: meta.reportingDate must be a string."
        )

    if dataset_date != reporting_date:
        raise ValueError(
            f"{dataset_name}: normalized data is for reporting date "
            f"{dataset_date}, but snapshot requested "
            f"{reporting_date}."
        )

    processed_at = meta.get(
        "processedAt"
    )

    if processed_at is not None and parse_iso_datetime(
        processed_at
    ) is None:
        raise ValueError(
            f"{dataset_name}: meta.processedAt is not valid ISO-8601."
        )


def _processed_at(
    dataset: dict[str, Any] | None,
) -> datetime | None:
    """Extract a valid processedAt timestamp."""
    value = _safe_meta(
        dataset
    ).get(
        "processedAt"
    )

    if value is None:
        return None

    return parse_iso_datetime(
        value
    )


def process_daily(
    reporting_date: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Create the daily snapshot from normalized datasets."""

    _validate_reporting_date(
        reporting_date,
        "reporting_date",
    )

    if window_start >= window_end:
        raise ValueError(
            "window_start must be earlier than window_end."
        )

    covered_ist_day = ist_date_of(
        window_start
    )

    expected_start, expected_end = (
        ist_day_window(reporting_date)
    )

    # For the normal edition window, ensure the reporting label and
    # coverage window cannot silently disagree.
    if (
        window_start == expected_start
        and window_end == expected_end
    ):
        covered_ist_day = (
            parse_ist_date(reporting_date)
            - timedelta(days=1)
        ).isoformat()

    print(
        f"Creating daily snapshot for "
        f"{reporting_date}..."
    )

    security = load_json(
        NORMALIZED_DIR / "security.json"
    )
    releases = load_json(
        NORMALIZED_DIR / "releases.json"
    )
    opensource = load_json(
        NORMALIZED_DIR / "opensource.json"
    )
    tech = load_json(
        NORMALIZED_DIR / "tech.json"
    )

    _validate_normalized_dataset(
        security,
        "security",
        reporting_date,
    )
    _validate_normalized_dataset(
        releases,
        "releases",
        reporting_date,
    )
    _validate_normalized_dataset(
        opensource,
        "opensource",
        reporting_date,
    )
    _validate_normalized_dataset(
        tech,
        "technology",
        reporting_date,
    )

    security_summary = _safe_summary(
        security
    )
    releases_summary = _safe_summary(
        releases
    )
    opensource_summary = _safe_summary(
        opensource
    )
    tech_summary = _safe_summary(
        tech
    )

    sources = {
        "nvd": _source_block(
            security,
            "nvd",
        ),
        "cisa": _source_block(
            security,
            "cisa",
        ),
        "github_releases": _source_block(
            releases,
            "github",
        ),
        "github_repos": _source_block(
            opensource,
            "github",
        ),
        "rss": _source_block(
            tech,
            "rss",
        ),
    }

    # Deterministic generation timestamp: newest processedAt across
    # normalized inputs. This keeps identical inputs deterministic.
    stamps: list[datetime] = []

    for dataset in (
        security,
        releases,
        opensource,
        tech,
    ):
        stamp = _processed_at(
            dataset
        )

        if stamp is not None:
            stamps.append(
                stamp
            )

    generated_at = (
        max(stamps).isoformat()
        if stamps
        else window_start.isoformat()
    )

    severity = security_summary.get(
        "severity",
        {}
    )

    if not isinstance(
        severity,
        dict,
    ):
        severity = {}

    latest_vulns = (
        security.get(
            "latest",
            []
        )[:10]
        if isinstance(
            security,
            dict
        )
        and isinstance(
            security.get(
                "latest",
                []
            ),
            list,
        )
        else []
    )

    kev_recent = (
        security.get(
            "kevRecent",
            []
        )[:5]
        if isinstance(
            security,
            dict
        )
        and isinstance(
            security.get(
                "kevRecent",
                []
            ),
            list,
        )
        else []
    )

    recent_releases = (
        releases.get(
            "releases",
            []
        )[:10]
        if isinstance(
            releases,
            dict
        )
        and isinstance(
            releases.get(
                "releases",
                []
            ),
            list,
        )
        else []
    )

    top_projects = (
        opensource.get(
            "topProjects",
            []
        )[:10]
        if isinstance(
            opensource,
            dict
        )
        and isinstance(
            opensource.get(
                "topProjects",
                []
            ),
            list,
        )
        else []
    )

    recent_entries = (
        tech.get(
            "entries",
            []
        )[:10]
        if isinstance(
            tech,
            dict
        )
        and isinstance(
            tech.get(
                "entries",
                []
            ),
            list,
        )
        else []
    )

    def brief_vuln(
        vulnerability: dict[str, Any],
    ) -> dict[str, Any]:
        cvss = vulnerability.get(
            "cvss"
        )

        score = (
            cvss.get("score")
            if isinstance(
                cvss,
                dict,
            )
            else None
        )

        cve_id = vulnerability.get(
            "id"
        )

        return {
            "id": cve_id,
            "severity": vulnerability.get(
                "severity"
            ),
            "cvss": score,
            "known_exploited": vulnerability.get(
                "known_exploited",
                False,
            ),
            "description": (
                vulnerability.get(
                    "description"
                )
                or ""
            )[:200],
            "url": (
                "https://nvd.nist.gov/vuln/detail/"
                f"{cve_id}"
                if cve_id
                else None
            ),
        }

    def brief_release(
        release: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "project": release.get(
                "project"
            ),
            "repository": release.get(
                "repository"
            ),
            "version": release.get(
                "version"
            ),
            "published_at": release.get(
                "published_at"
            ),
            "url": release.get(
                "url"
            ),
        }

    def brief_project(
        project: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "full_name": project.get(
                "full_name"
            ),
            "stars": project.get(
                "stars"
            ),
            "daily_growth": project.get(
                "daily_growth"
            ),
            "language": project.get(
                "language"
            ),
            "url": project.get(
                "url"
            ),
        }

    def brief_entry(
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": entry.get(
                "title"
            ),
            "url": entry.get(
                "url"
            ),
            "source": entry.get(
                "feed_source"
            ),
            "published_at": entry.get(
                "published_at"
            ),
        }

    snapshot: dict[str, Any] = {
        "date": reporting_date,
        "coveredIstDay": covered_ist_day,
        "generatedAt": generated_at,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "timezone": "Asia/Kolkata",
        },
        "snapshot": {
            "cves": _safe_nonnegative_int(
                security_summary.get(
                    "total"
                )
            ),
            "knownExploited": _safe_nonnegative_int(
                security_summary.get(
                    "knownExploited"
                )
            ),
            "kevAdded": _safe_nonnegative_int(
                security_summary.get(
                    "kevAddedInWindow"
                )
            ),
            "releases": _safe_nonnegative_int(
                releases_summary.get(
                    "total"
                )
            ),
            "projects": _safe_nonnegative_int(
                opensource_summary.get(
                    "totalTracked"
                )
            ),
            "techEntries": _safe_nonnegative_int(
                tech_summary.get(
                    "total"
                )
            ),
        },
        "security": {
            "severity": severity,
            "latest": [
                brief_vuln(v)
                for v in latest_vulns
                if isinstance(
                    v,
                    dict,
                )
            ],
            "kevRecent": [
                {
                    "cve_id": vulnerability.get(
                        "cve_id"
                    ),
                    "vendor_project": vulnerability.get(
                        "vendor_project"
                    ),
                    "product": vulnerability.get(
                        "product"
                    ),
                    "vulnerability_name": vulnerability.get(
                        "vulnerability_name"
                    ),
                    "date_added": vulnerability.get(
                        "date_added"
                    ),
                }
                for vulnerability in kev_recent
                if isinstance(
                    vulnerability,
                    dict,
                )
            ],
        },
        "releases": {
            "categories": (
                releases_summary.get(
                    "categories",
                    {}
                )
                if isinstance(
                    releases_summary.get(
                        "categories",
                        {}
                    ),
                    dict,
                )
                else {}
            ),
            "recent": [
                brief_release(r)
                for r in recent_releases
                if isinstance(
                    r,
                    dict,
                )
            ],
        },
        "opensource": {
            "growthBasis": opensource_summary.get(
                "growthBasis",
                "unavailable",
            ),
            "topProjects": [
                brief_project(p)
                for p in top_projects
                if isinstance(
                    p,
                    dict,
                )
            ],
        },
        "technology": {
            "categories": (
                tech_summary.get(
                    "categories",
                    {}
                )
                if isinstance(
                    tech_summary.get(
                        "categories",
                        {}
                    ),
                    dict,
                )
                else {}
            ),
            "sources": (
                tech_summary.get(
                    "sources",
                    {}
                )
                if isinstance(
                    tech_summary.get(
                        "sources",
                        {}
                    ),
                    dict,
                )
                else {}
            ),
            "recent": [
                brief_entry(e)
                for e in recent_entries
                if isinstance(
                    e,
                    dict,
                )
            ],
        },
        "sources": sources,
    }

    return snapshot


def save_daily_snapshot(
    snapshot: dict[str, Any],
) -> Path:
    """
    Save an idempotent daily snapshot.

    If an existing snapshot has identical content it is preserved.
    When content changes, the file is deliberately replaced with the
    newly generated snapshot rather than silently pretending the file
    is append-only.
    """

    if not isinstance(
        snapshot,
        dict,
    ):
        raise ValueError(
            "snapshot must be an object."
        )

    snapshot_date = snapshot.get(
        "date"
    )

    if not isinstance(
        snapshot_date,
        str,
    ):
        raise ValueError(
            "snapshot.date must be a YYYY-MM-DD string."
        )

    _validate_reporting_date(
        snapshot_date,
        "snapshot.date",
    )

    if not isinstance(
        snapshot.get(
            "snapshot"
        ),
        dict,
    ):
        raise ValueError(
            "snapshot.snapshot must be an object."
        )

    DAILY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        DAILY_DIR
        / f"{snapshot_date}.json"
    )

    if output_path.exists():
        try:
            existing = json.loads(
                output_path.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(
                existing,
                dict,
            ) and (
                snapshot_fingerprint(existing)
                == snapshot_fingerprint(snapshot)
            ):
                print(
                    f"Snapshot for {snapshot_date} "
                    "unchanged; keeping existing file."
                )
                return output_path

            print(
                f"Snapshot for {snapshot_date} "
                "changed; replacing existing snapshot."
            )

        except (
            json.JSONDecodeError,
            OSError,
        ):
            print(
                f"Existing snapshot for {snapshot_date} "
                "is unreadable; replacing it."
            )

    save_json(
        snapshot,
        output_path,
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create the TechPulse daily snapshot."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date "
            "(YYYY-MM-DD, IST edition)."
        ),
    )

    parser.add_argument(
        "--start",
        help=(
            "Window start override "
            "(ISO-8601)."
        ),
    )

    parser.add_argument(
        "--end",
        help=(
            "Window end override "
            "(ISO-8601, exclusive)."
        ),
    )

    args = parser.parse_args()

    try:
        reporting_date = resolve_snapshot_date(
            args.date,
            args.start,
            args.end,
        )

        window_start, window_end = (
            resolve_window(
                reporting_date,
                args.start,
                args.end,
            )
        )

    except ValueError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    covered_ist_day = ist_date_of(
        window_start
    )

    print()
    print(
        "TechPulse — Daily Snapshot Processor"
    )
    print("=" * 32)
    print(
        f"Reporting date : "
        f"{reporting_date} (IST edition)"
    )
    print(
        f"Covers IST day : "
        f"{covered_ist_day}"
    )
    print(
        f"Window         : "
        f"{window_start.isoformat()} -> "
        f"{window_end.isoformat()}"
    )
    print()

    try:
        snapshot = process_daily(
            reporting_date,
            window_start,
            window_end,
        )

        output_path = save_daily_snapshot(
            snapshot
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    counts = snapshot[
        "snapshot"
    ]

    print()
    print(
        "Daily snapshot created."
    )
    print(
        f"Date      : {snapshot['date']}"
    )
    print(
        f"CVEs      : {counts['cves']}"
    )
    print(
        f"Releases  : {counts['releases']}"
    )
    print(
        f"Projects  : {counts['projects']}"
    )
    print(
        f"Tech      : {counts['techEntries']}"
    )
    print(
        f"Output    : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
