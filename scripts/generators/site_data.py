#!/usr/bin/env python3

"""
TechPulse — Site Data Generator

Generates the main frontend data file (generated/data.json) from the
normalized datasets.

Date handling:
    - meta.date is the TechPulse reporting date — a date-only India
      calendar day (Asia/Kolkata).
    - Normalized reporting datasets must belong to that same reporting
      date. Cross-date input is rejected.
    - The frontend receives ISO timestamps and computes relative labels
      at render time; relative strings are never frozen into the data.

Determinism:
    The generation timestamp is derived from the normalized inputs,
    so reprocessing identical inputs produces byte-identical output.
    No wall-clock reads occur during normal generation.

Integrity:
    - Missing required normalized datasets are fatal.
    - Invalid normalized datasets are fatal.
    - Cross-reporting-date normalized inputs are fatal.
    - Future-dated history entries are excluded from the generated
      dataset when generating a backfilled edition.

Output:
    generated/data.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    GENERATED_DIR,
    NORMALIZED_DIR,
    ist_day_window,
    ist_date_of,
    ist_today,
    load_json,
    parse_iso_datetime,
    parse_ist_date,
    save_json,
)


REQUIRED_NORMALIZED_DATASETS = {
    "security": NORMALIZED_DIR / "security.json",
    "releases": NORMALIZED_DIR / "releases.json",
    "opensource": NORMALIZED_DIR / "opensource.json",
    "tech": NORMALIZED_DIR / "tech.json",
    "history": NORMALIZED_DIR / "history.json",
}


def validate_reporting_date(
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
) -> str:
    """Resolve and validate the target reporting date."""
    if date_arg:
        return validate_reporting_date(
            date_arg,
            "--date",
        )

    snapshot_date = ist_today()

    return validate_reporting_date(
        snapshot_date,
        "current reporting date",
    )


def truncate(
    text: str,
    limit: int = 160,
) -> str:
    """Truncate text deterministically."""
    if not text:
        return ""

    if len(text) <= limit:
        return text

    truncated = text[:limit].rsplit(
        " ",
        1,
    )[0].rstrip(
        ",.;:"
    )

    return truncated + "…"


def _load_required_dataset(
    name: str,
    path: Path,
    reporting_date: str,
) -> dict[str, Any]:
    """
    Load one required normalized dataset and verify its reporting date.
    """

    if not path.is_file():
        raise ValueError(
            f"Required normalized dataset is missing: "
            f"{path}"
        )

    data = load_json(path)

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            f"{name}: normalized dataset must be a JSON object."
        )

    meta = data.get(
        "meta",
        {}
    )

    if not isinstance(
        meta,
        dict,
    ):
        raise ValueError(
            f"{name}: normalized dataset meta must be an object."
        )

    # History is an archive-wide index and deliberately does not carry
    # a reportingDate field.
    if name != "history":
        dataset_date = meta.get(
            "reportingDate"
        )

        if not isinstance(
            dataset_date,
            str,
        ):
            raise ValueError(
                f"{name}: normalized dataset is missing "
                "meta.reportingDate."
            )

        if dataset_date != reporting_date:
            raise ValueError(
                f"{name}: normalized dataset is for "
                f"reporting date {dataset_date}, but "
                f"{reporting_date} was requested."
            )

        validate_reporting_date(
            dataset_date,
            f"{name}.meta.reportingDate",
        )

    processed_at = meta.get(
        "processedAt"
    )

    if processed_at is not None and (
        parse_iso_datetime(
            processed_at
        )
        is None
    ):
        raise ValueError(
            f"{name}: meta.processedAt is not a valid "
            "ISO-8601 timestamp."
        )

    return data


def _safe_summary(
    dataset: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Return a validated summary object."""
    summary = dataset.get(
        "summary",
        {}
    )

    if not isinstance(
        summary,
        dict,
    ):
        raise ValueError(
            f"{name}: summary must be an object."
        )

    return summary


def _safe_list(
    dataset: dict[str, Any],
    key: str,
    name: str,
) -> list[Any]:
    """Return a validated list field."""
    value = dataset.get(
        key,
        []
    )

    if not isinstance(
        value,
        list,
    ):
        raise ValueError(
            f"{name}: '{key}' must be a list."
        )

    return value


def _safe_nonnegative_int(
    value: Any,
    field_name: str,
) -> int:
    """Validate a non-negative integer count."""
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            int,
        )
        or value < 0
    ):
        raise ValueError(
            f"{field_name} must be a "
            "non-negative integer."
        )

    return value


def _safe_sources(
    dataset: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Return a validated source-health object."""
    meta = dataset.get(
        "meta",
        {}
    )

    sources = meta.get(
        "sources",
        {}
    )

    if not isinstance(
        sources,
        dict,
    ):
        raise ValueError(
            f"{name}: meta.sources must be an object."
        )

    return sources


def format_cve(
    cve: dict[str, Any],
) -> dict[str, Any]:
    """Format an NVD record for frontend display."""

    if not isinstance(
        cve,
        dict,
    ):
        raise ValueError(
            "Security dataset contains a non-object CVE record."
        )

    cvss = cve.get(
        "cvss"
    )

    if cvss is not None and not isinstance(
        cvss,
        dict,
    ):
        cvss = None

    description = cve.get(
        "description"
    )

    if not isinstance(
        description,
        str,
    ):
        description = ""

    cve_id = cve.get(
        "id"
    )

    if cve_id is not None and not isinstance(
        cve_id,
        str,
    ):
        raise ValueError(
            "CVE record id must be a string or null."
        )

    return {
        "id": cve_id or "",
        "title": (
            truncate(description)
            or "(no description available)"
        ),
        "description": truncate(
            description,
            400,
        ),
        "severity": cve.get(
            "severity"
        ),
        "cvss_score": (
            cvss.get("score")
            if cvss
            else None
        ),
        "cvss_version": (
            cvss.get("version")
            if cvss
            else None
        ),
        # ISO timestamps — the frontend renders live relative labels.
        "publishedAt": cve.get(
            "published"
        ) or None,
        "lastModifiedAt": cve.get(
            "lastModified"
        ) or None,
        "known_exploited": bool(
            cve.get(
                "known_exploited"
            )
        ),
        "url": (
            "https://nvd.nist.gov/vuln/detail/"
            f"{cve_id}"
            if cve_id
            else ""
        ),
        "source": "NVD",
    }


def format_release(
    release: dict[str, Any],
) -> dict[str, Any]:
    """Format a GitHub release for frontend display."""

    if not isinstance(
        release,
        dict,
    ):
        raise ValueError(
            "Release dataset contains a non-object record."
        )

    return {
        "project": release.get(
            "project"
        ) or "",
        "repository": release.get(
            "repository"
        ) or "",
        "version": release.get(
            "version"
        ) or "",
        "kind": release.get(
            "kind"
        ) or "other",
        "publishedAt": release.get(
            "published_at"
        ) or None,
        "url": release.get(
            "url"
        ) or "",
        "source": release.get(
            "source"
        ) or "GitHub",
    }


def format_project(
    project: dict[str, Any],
) -> dict[str, Any]:
    """Format a GitHub repository for frontend display."""

    if not isinstance(
        project,
        dict,
    ):
        raise ValueError(
            "Open-source dataset contains a non-object record."
        )

    return {
        "rank": project.get(
            "rank",
            0,
        ),
        "name": project.get(
            "name"
        ) or "",
        "full_name": project.get(
            "full_name"
        ) or "",
        "description": project.get(
            "description"
        ) or "",
        "stars": project.get(
            "stars"
        ),
        "daily_growth": project.get(
            "daily_growth"
        ),
        "growth_available": bool(
            project.get(
                "growth_available"
            )
        ),
        "language": project.get(
            "language"
        ) or "",
        "url": project.get(
            "url"
        ) or "",
        "source": "GitHub",
    }


def format_tech_entry(
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Format a technology/RSS entry for frontend display."""

    if not isinstance(
        entry,
        dict,
    ):
        raise ValueError(
            "Technology dataset contains a non-object record."
        )

    return {
        "title": truncate(
            entry.get("title") or "",
            200,
        ),
        "url": entry.get(
            "url"
        ) or "",
        "source": entry.get(
            "feed_source"
        ) or "",
        "category": entry.get(
            "feed_category"
        ) or "tech",
        "publishedAt": entry.get(
            "published_at"
        ) or None,
        "summary": truncate(
            entry.get("summary") or "",
            280,
        ),
    }


def _validated_history(
    history_dataset: dict[str, Any],
    snapshot_date: str,
) -> list[dict[str, Any]]:
    """
    Return valid historical records up to the requested reporting date.

    Future-dated records are intentionally excluded so a backfilled
    site-data generation cannot expose snapshots newer than itself.
    """

    raw_history = _safe_list(
        history_dataset,
        "history",
        "history",
    )

    output: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    target_date = parse_ist_date(
        snapshot_date
    )

    if target_date is None:
        raise ValueError(
            "Invalid snapshot date while validating history."
        )

    for index, item in enumerate(
        raw_history,
        start=1,
    ):
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                f"history.history record #{index} "
                "must be an object."
            )

        date = item.get(
            "date"
        )

        if not isinstance(
            date,
            str,
        ) or parse_ist_date(date) is None:
            raise ValueError(
                f"history.history record #{index} "
                "has an invalid date."
            )

        if date in seen_dates:
            raise ValueError(
                f"history.history contains duplicate date "
                f"{date}."
            )

        seen_dates.add(
            date
        )

        history_date = parse_ist_date(
            date
        )

        if history_date > target_date:
            continue

        normalized = {
            "date": date,
            "cves": _safe_nonnegative_int(
                item.get(
                    "cves",
                    0,
                ),
                f"history.{date}.cves",
            ),
            "knownExploited": _safe_nonnegative_int(
                item.get(
                    "knownExploited",
                    0,
                ),
                f"history.{date}.knownExploited",
            ),
            "kevAdded": _safe_nonnegative_int(
                item.get(
                    "kevAdded",
                    0,
                ),
                f"history.{date}.kevAdded",
            ),
            "releases": _safe_nonnegative_int(
                item.get(
                    "releases",
                    0,
                ),
                f"history.{date}.releases",
            ),
            "projects": _safe_nonnegative_int(
                item.get(
                    "projects",
                    0,
                ),
                f"history.{date}.projects",
            ),
            "techEntries": _safe_nonnegative_int(
                item.get(
                    "techEntries",
                    0,
                ),
                f"history.{date}.techEntries",
            ),
        }

        output.append(
            normalized
        )

    # History processor emits newest first. Enforce that deterministic
    # ordering here too, independent of upstream implementation details.
    output.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    return output


def _generated_at(
    datasets: list[dict[str, Any]],
    snapshot_date: str,
) -> str:
    """
    Derive a deterministic generation timestamp from the reporting
    datasets used for the current edition.

    History is intentionally excluded because its processedAt represents
    the archive index as a whole, not the requested reporting edition.
    """

    stamps = []

    for dataset in datasets:
        meta = dataset.get(
            "meta",
            {}
        )

        if not isinstance(
            meta,
            dict,
        ):
            continue

        processed_at = meta.get(
            "processedAt"
        )

        if processed_at is None:
            continue

        parsed = parse_iso_datetime(
            processed_at
        )

        if parsed is not None:
            stamps.append(
                parsed
            )

    if stamps:
        return max(
            stamps
        ).isoformat()

    # Deterministic fallback: the reporting-date midnight in UTC.
    parsed_date = parse_ist_date(
        snapshot_date
    )

    if parsed_date is None:
        raise ValueError(
            "Cannot derive generatedAt from invalid reporting date."
        )

    return (
        parsed_date
        .replace(
            tzinfo=None
        )
        .isoformat()
        + "T00:00:00+00:00"
    )


def generate_site_data(
    snapshot_date: str,
) -> dict[str, Any]:
    """Generate the complete frontend dataset."""

    snapshot_date = validate_reporting_date(
        snapshot_date
    )

    print(
        "Loading normalized data..."
    )

    datasets = {
        name: _load_required_dataset(
            name,
            path,
            snapshot_date,
        )
        for name, path
        in REQUIRED_NORMALIZED_DATASETS.items()
    }

    security = datasets["security"]
    releases = datasets["releases"]
    opensource = datasets["opensource"]
    tech = datasets["tech"]
    history = datasets["history"]

    security_summary = _safe_summary(
        security,
        "security",
    )

    releases_summary = _safe_summary(
        releases,
        "releases",
    )

    opensource_summary = _safe_summary(
        opensource,
        "opensource",
    )

    tech_summary = _safe_summary(
        tech,
        "tech",
    )

    security_sources = _safe_sources(
        security,
        "security",
    )

    releases_sources = _safe_sources(
        releases,
        "releases",
    )

    opensource_sources = _safe_sources(
        opensource,
        "opensource",
    )

    tech_sources = _safe_sources(
        tech,
        "tech",
    )

    severity = security_summary.get(
        "severity",
        {}
    )

    if not isinstance(
        severity,
        dict,
    ):
        raise ValueError(
            "security.summary.severity must be an object."
        )

    security_latest = _safe_list(
        security,
        "latest",
        "security",
    )

    releases_list = _safe_list(
        releases,
        "releases",
        "releases",
    )

    opensource_projects = _safe_list(
        opensource,
        "topProjects",
        "opensource",
    )

    tech_entries = _safe_list(
        tech,
        "entries",
        "tech",
    )

    history_list = _validated_history(
        history,
        snapshot_date,
    )

    generated_at = _generated_at(
        [
            security,
            releases,
            opensource,
            tech,
        ],
        snapshot_date,
    )

    # The edition for reporting date X covers the previous IST day.
    window_start, _ = ist_day_window(
        snapshot_date
    )

    covered_date = ist_date_of(
        window_start
    )

    return {
        "meta": {
            "date": snapshot_date,
            "coveredDate": covered_date,
            "timezone": "Asia/Kolkata",
            "generatedAt": generated_at,
            "daysObserved": len(
                history_list
            ),
            "snapshots": len(
                history_list
            ),
        },
        "snapshot": {
            "cves": _safe_nonnegative_int(
                security_summary.get(
                    "total",
                    0,
                ),
                "security.summary.total",
            ),
            "knownExploited": _safe_nonnegative_int(
                security_summary.get(
                    "knownExploited",
                    0,
                ),
                "security.summary.knownExploited",
            ),
            "kevAdded": _safe_nonnegative_int(
                security_summary.get(
                    "kevAddedInWindow",
                    0,
                ),
                "security.summary.kevAddedInWindow",
            ),
            "releases": _safe_nonnegative_int(
                releases_summary.get(
                    "total",
                    0,
                ),
                "releases.summary.total",
            ),
            "projects": _safe_nonnegative_int(
                opensource_summary.get(
                    "totalTracked",
                    0,
                ),
                "opensource.summary.totalTracked",
            ),
            "techEntries": _safe_nonnegative_int(
                tech_summary.get(
                    "total",
                    0,
                ),
                "tech.summary.total",
            ),
        },
        "security": {
            "critical": _safe_nonnegative_int(
                severity.get(
                    "CRITICAL",
                    0,
                ),
                "security.severity.CRITICAL",
            ),
            "high": _safe_nonnegative_int(
                severity.get(
                    "HIGH",
                    0,
                ),
                "security.severity.HIGH",
            ),
            "medium": _safe_nonnegative_int(
                severity.get(
                    "MEDIUM",
                    0,
                ),
                "security.severity.MEDIUM",
            ),
            "low": _safe_nonnegative_int(
                severity.get(
                    "LOW",
                    0,
                ),
                "security.severity.LOW",
            ),
            "none": _safe_nonnegative_int(
                severity.get(
                    "NONE",
                    0,
                ),
                "security.severity.NONE",
            ),
            "unscored": _safe_nonnegative_int(
                severity.get(
                    "UNSCORED",
                    0,
                ),
                "security.severity.UNSCORED",
            ),
            "kevCatalogTotal": _safe_nonnegative_int(
                security_summary.get(
                    "kevCatalogTotal",
                    0,
                ),
                "security.summary.kevCatalogTotal",
            ),
            "latest": [
                format_cve(
                    cve
                )
                for cve in security_latest[:15]
            ],
        },
        "releases": [
            format_release(
                release
            )
            for release in releases_list[:30]
        ],
        "openSource": [
            format_project(
                project
            )
            for project in opensource_projects[:12]
        ],
        "technology": [
            format_tech_entry(
                entry
            )
            for entry in tech_entries[:15]
        ],
        "history": history_list,
        "sources": {
            "security": security_sources,
            "releases": releases_sources,
            "opensource": opensource_sources,
            "technology": tech_sources,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the frontend site data."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date "
            "(YYYY-MM-DD, IST edition)."
        ),
    )

    args = parser.parse_args()

    try:
        snapshot_date = resolve_snapshot_date(
            args.date
        )
    except ValueError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        "TechPulse — Site Data Generator"
    )
    print("=" * 32)
    print(
        f"Reporting date: {snapshot_date}"
    )
    print()

    try:
        data = generate_site_data(
            snapshot_date
        )

        output_path = (
            GENERATED_DIR
            / "data.json"
        )

        save_json(
            data,
            output_path,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        "Generation completed."
    )
    print(
        f"Snapshot : {data['meta']['date']}"
    )
    print(
        f"CVEs     : {data['snapshot']['cves']}"
    )
    print(
        f"Releases : {data['snapshot']['releases']}"
    )
    print(
        f"Projects : {data['snapshot']['projects']}"
    )
    print(
        f"Output   : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
