#!/usr/bin/env python3

"""
TechPulse — Offline Validator

Performs full offline repository validation. Never touches the network.

Checks:
    1. Python syntax (every tracked .py file compiles)
    2. JSON validity (every .json file parses)
    3. Expected directory structure
    4. Configuration files present and structurally sane
    5. Frontend files present; JS/CSS references and internal links resolve
    6. Placeholder / fake-data detection
    7. Generated data schema sanity
    8. Raw data schema sanity
    9. Raw snapshot date and metadata consistency

Run:
    python3 scripts/validate.py

Exit codes:
    0 — all checks passed (or no generated/raw data exists yet)
    1 — one or more checks failed
"""

from __future__ import annotations

import json
import py_compile
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FAILURES: list[str] = []
WARNINGS: list[str] = []

REPORTING_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}$"
)

CVE_ID_PATTERN = re.compile(
    r"^CVE-\d{4}-\d{4,}$",
    re.IGNORECASE,
)

ISO_RELATIVE_LABEL_PATTERN = re.compile(
    r"^(Today|Yesterday|\d+ days ago)$",
    re.IGNORECASE,
)


def fail(message: str) -> None:
    FAILURES.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def reset_results() -> None:
    """Reset accumulated validation state."""
    FAILURES.clear()
    WARNINGS.clear()


def is_valid_reporting_date(value: Any) -> bool:
    """Return True only for a real YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        return False

    if not REPORTING_DATE_PATTERN.fullmatch(value):
        return False

    try:
        datetime.strptime(
            value,
            "%Y-%m-%d",
        )
    except ValueError:
        return False

    return True


def parse_iso_timestamp(value: Any) -> bool:
    """Return True when value is a valid ISO-8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        return False

    try:
        datetime.fromisoformat(
            value.strip().replace(
                "Z",
                "+00:00",
            )
        )
        return True
    except ValueError:
        return False


def relative_path(path: Path) -> str:
    """Return a project-relative path for diagnostics."""
    try:
        return str(
            path.relative_to(PROJECT_ROOT)
        )
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ #
# 1. Python syntax
# ------------------------------------------------------------------ #

def check_python_syntax() -> None:
    section("1. Python syntax")

    py_files = sorted(
        p
        for p in PROJECT_ROOT.rglob("*.py")
        if ".git" not in p.parts
        and "__pycache__" not in p.parts
    )

    if not py_files:
        fail("No Python files found")
        return

    errors = 0

    for path in py_files:
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as exc:
            fail(
                f"Syntax error in "
                f"{relative_path(path)}: {exc}"
            )
            errors += 1

    status = (
        "OK"
        if errors == 0
        else "FAILED"
    )

    print(
        f"  {len(py_files)} files checked: {status}"
    )


# ------------------------------------------------------------------ #
# 2. JSON validity
# ------------------------------------------------------------------ #

def check_json_validity() -> None:
    section("2. JSON validity")

    json_files = sorted(
        p
        for p in PROJECT_ROOT.rglob("*.json")
        if ".git" not in p.parts
        and "__pycache__" not in p.parts
    )

    if not json_files:
        warn("No JSON files found")
        return

    errors = 0

    for path in json_files:
        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as f:
                json.load(f)

        except (
            json.JSONDecodeError,
            OSError,
        ) as exc:
            fail(
                f"Invalid JSON in "
                f"{relative_path(path)}: {exc}"
            )
            errors += 1

    status = (
        "OK"
        if errors == 0
        else "FAILED"
    )

    print(
        f"  {len(json_files)} files checked: {status}"
    )


# ------------------------------------------------------------------ #
# 3. Expected structure
# ------------------------------------------------------------------ #

EXPECTED_PATHS = [
    "scripts/run_pipeline.py",
    "scripts/reporting_date.py",
    "scripts/validate.py",
    "scripts/sources/nvd/collect.py",
    "scripts/sources/cisa/collect.py",
    "scripts/sources/github/collect.py",
    "scripts/sources/rss/collect.py",
    "scripts/processors/security.py",
    "scripts/processors/releases.py",
    "scripts/processors/opensource.py",
    "scripts/processors/tech.py",
    "scripts/processors/daily.py",
    "scripts/processors/history.py",
    "scripts/processors/utils.py",
    "scripts/generators/site_data.py",
    "scripts/generators/archive.py",
    "scripts/config/snapshot.json",
    "scripts/config/github.json",
    "scripts/config/rss.json",
    "src/index.html",
    "src/security.html",
    "src/releases.html",
    "src/opensource.html",
    "src/history.html",
    "src/js/data.js",
    "src/js/dates.js",
    "src/js/components.js",
    "src/js/app.js",
    "src/assets/favicon.svg",
    "src/css/base.css",
    "src/css/layout.css",
    "src/css/components.css",
    ".github/workflows",
    "README.md",
    "LICENSE",
]


def check_structure() -> None:
    section("3. Expected structure")

    missing = [
        path
        for path in EXPECTED_PATHS
        if not (
            PROJECT_ROOT / path
        ).exists()
    ]

    for path in missing:
        fail(
            f"Missing expected path: {path}"
        )

    print(
        f"  {len(EXPECTED_PATHS) - len(missing)}/"
        f"{len(EXPECTED_PATHS)} present"
    )


# ------------------------------------------------------------------ #
# 4. Configuration sanity
# ------------------------------------------------------------------ #

def check_configs() -> None:
    section("4. Configuration sanity")

    # -------------------------------------------------------------- #
    # GitHub config
    # -------------------------------------------------------------- #

    github_config = (
        PROJECT_ROOT
        / "scripts"
        / "config"
        / "github.json"
    )

    try:
        data = json.loads(
            github_config.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            fail(
                "github.json: root must be an object"
            )
        else:
            repos = data.get(
                "tracked_repositories",
                [],
            )

            if not isinstance(
                repos,
                list,
            ):
                fail(
                    "github.json: "
                    "tracked_repositories must be a list"
                )
            elif not repos:
                fail(
                    "github.json: "
                    "no tracked repositories configured"
                )
            else:
                invalid = 0
                seen_repositories: set[str] = set()

                for repo in repos:
                    if not isinstance(
                        repo,
                        dict,
                    ):
                        invalid += 1
                        continue

                    owner = repo.get(
                        "owner"
                    )
                    name = repo.get(
                        "repo"
                    )

                    if not (
                        isinstance(
                            owner,
                            str,
                        )
                        and owner.strip()
                        and isinstance(
                            name,
                            str,
                        )
                        and name.strip()
                    ):
                        invalid += 1
                        continue

                    identity = (
                        f"{owner.strip().lower()}/"
                        f"{name.strip().lower()}"
                    )

                    if identity in seen_repositories:
                        fail(
                            "github.json: duplicate "
                            f"tracked repository '{identity}'"
                        )

                    seen_repositories.add(
                        identity
                    )

                if invalid:
                    fail(
                        "github.json: "
                        f"{invalid} invalid "
                        "tracked_repositories entries"
                    )

                collection = data.get(
                    "collection",
                    {},
                )

                if not isinstance(
                    collection,
                    dict,
                ):
                    fail(
                        "github.json: "
                        "collection must be an object"
                    )
                else:
                    for key in (
                        "max_releases_per_repo",
                        "rate_limit_delay_seconds",
                    ):
                        if key not in collection:
                            continue

                        value = collection[key]

                        if isinstance(
                            value,
                            bool,
                        ):
                            fail(
                                f"github.json: "
                                f"collection.{key} "
                                "must be numeric"
                            )

                print(
                    f"  github.json: "
                    f"{len(repos)} tracked repositories checked"
                )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        fail(
            f"github.json unreadable: {exc}"
        )

    # -------------------------------------------------------------- #
    # RSS config
    # -------------------------------------------------------------- #

    rss_config = (
        PROJECT_ROOT
        / "scripts"
        / "config"
        / "rss.json"
    )

    try:
        data = json.loads(
            rss_config.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):
            fail(
                "rss.json: root must be an object"
            )
        else:
            feeds = data.get(
                "feeds",
                [],
            )

            if not isinstance(
                feeds,
                list,
            ):
                fail(
                    "rss.json: feeds must be a list"
                )
            elif not feeds:
                fail(
                    "rss.json: "
                    "no feeds configured"
                )
            else:
                invalid = 0
                seen_urls: set[str] = set()

                for feed in feeds:
                    if not isinstance(
                        feed,
                        dict,
                    ):
                        invalid += 1
                        continue

                    url = feed.get(
                        "url"
                    )

                    if not (
                        isinstance(
                            url,
                            str,
                        )
                        and url.strip()
                    ):
                        invalid += 1
                        continue

                    url = url.strip()

                    if not (
                        url.startswith(
                            "http://"
                        )
                        or url.startswith(
                            "https://"
                        )
                    ):
                        fail(
                            "rss.json: feed URL must "
                            f"use HTTP/HTTPS: {url}"
                        )

                    normalized_url = (
                        url.lower()
                    )

                    if normalized_url in seen_urls:
                        fail(
                            "rss.json: duplicate "
                            f"feed URL: {url}"
                        )

                    seen_urls.add(
                        normalized_url
                    )

                if invalid:
                    fail(
                        "rss.json: "
                        f"{invalid} invalid feed entries"
                    )

                collection = data.get(
                    "collection",
                    {},
                )

                if not isinstance(
                    collection,
                    dict,
                ):
                    fail(
                        "rss.json: "
                        "collection must be an object"
                    )

                print(
                    f"  rss.json: "
                    f"{len(feeds)} feeds checked"
                )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        fail(
            f"rss.json unreadable: {exc}"
        )

    # -------------------------------------------------------------- #
    # Snapshot config
    # -------------------------------------------------------------- #

    snapshot_config = (
        PROJECT_ROOT
        / "scripts"
        / "config"
        / "snapshot.json"
    )

    try:
        data = json.loads(
            snapshot_config.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):
            fail(
                "snapshot.json: root must be an object"
            )
        else:
            snapshot = data.get(
                "snapshot",
                {},
            )

            if not isinstance(
                snapshot,
                dict,
            ):
                fail(
                    "snapshot.json: snapshot "
                    "must be an object"
                )
            else:
                model = snapshot.get(
                    "model"
                )

                if model != "ist_reporting_day":
                    fail(
                        "snapshot.json: "
                        "snapshot.model must be "
                        "ist_reporting_day"
                    )
                else:
                    print(
                        "  snapshot.json: "
                        "ist_reporting_day model OK"
                    )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        fail(
            f"snapshot.json unreadable: {exc}"
        )


# ------------------------------------------------------------------ #
# 5. Frontend wiring
# ------------------------------------------------------------------ #

def check_frontend() -> None:
    section("5. Frontend wiring")

    pages = [
        "index.html",
        "security.html",
        "releases.html",
        "opensource.html",
        "history.html",
    ]

    required_scripts = (
        "js/data.js",
        "js/dates.js",
        "js/components.js",
        "js/app.js",
    )

    required_styles = (
        "css/base.css",
        "css/layout.css",
        "css/components.css",
    )

    for page in pages:
        path = (
            PROJECT_ROOT
            / "src"
            / page
        )

        try:
            html = path.read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            fail(
                f"{page} unreadable: {exc}"
            )
            continue

        for script in required_scripts:
            if script not in html:
                fail(
                    f"{page}: missing script "
                    f"reference {script}"
                )

            script_path = (
                PROJECT_ROOT
                / "src"
                / script
            )

            if not script_path.exists():
                fail(
                    f"{page}: referenced script "
                    f"does not exist: {script}"
                )

        for css in required_styles:
            if css not in html:
                fail(
                    f"{page}: missing stylesheet "
                    f"reference {css}"
                )

            css_path = (
                PROJECT_ROOT
                / "src"
                / css
            )

            if not css_path.exists():
                fail(
                    f"{page}: referenced stylesheet "
                    f"does not exist: {css}"
                )

        # Check relative .html links in both quoted forms.
        internal_links = re.findall(
            r"""(?:href|action)=["']([a-zA-Z0-9._-]+\.html)["']""",
            html,
        )

        for link in internal_links:
            if not (
                PROJECT_ROOT
                / "src"
                / link
            ).exists():
                fail(
                    f"{page}: broken internal "
                    f"link -> {link}"
                )

        title = re.search(
            r"<title>\s*(.*?)\s*</title>",
            html,
            flags=re.IGNORECASE
            | re.DOTALL,
        )

        if not title or not title.group(1).strip():
            fail(
                f"{page}: missing title"
            )

    # Brand consistency.
    for page in pages:
        path = (
            PROJECT_ROOT
            / "src"
            / page
        )

        try:
            html = path.read_text(
                encoding="utf-8"
            )
        except OSError:
            continue

        if 'brand-mark">TP<' in html:
            fail(
                f"{page}: inconsistent brand "
                "mark 'TP' (expected 'T')"
            )

    print(
        f"  {len(pages)} pages checked"
    )


# ------------------------------------------------------------------ #
# 6. Placeholder detection
# ------------------------------------------------------------------ #

PLACEHOLDER_PATTERNS = [
    "CVE-2026-XXXXX",
    "CVE-XXXX-XXXX",
    "Project Alpha",
    "Project Beta",
    "Project Gamma",
    "lorem ipsum",
    "v19.x.x",
    "v13.x.x",
    "v24.x.x",
    "v3.x.x",
    "v7.x.x",
]

PLACEHOLDER_SCAN_SUFFIXES = {
    ".html",
    ".js",
    ".css",
    ".py",
    ".json",
    ".md",
}


def check_placeholders() -> None:
    section("6. Placeholder detection")

    findings = 0
    self_path = Path(__file__).resolve()

    for path in PROJECT_ROOT.rglob("*"):
        if (
            ".git" in path.parts
            or "__pycache__" in path.parts
        ):
            continue

        if not path.is_file():
            continue

        if path.resolve() == self_path:
            continue

        if path.suffix.lower() not in (
            PLACEHOLDER_SCAN_SUFFIXES
        ):
            continue

        try:
            content = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        lowered = content.lower()

        for pattern in PLACEHOLDER_PATTERNS:
            if pattern.lower() in lowered:
                fail(
                    f"Placeholder '{pattern}' found "
                    f"in {relative_path(path)}"
                )
                findings += 1

    if findings == 0:
        print(
            "  No placeholder content found"
        )


# ------------------------------------------------------------------ #
# 7. Generated data schema
# ------------------------------------------------------------------ #

def check_generated_data() -> None:
    section("7. Generated data schema")

    data_path = (
        PROJECT_ROOT
        / "generated"
        / "data.json"
    )

    if not data_path.exists():
        warn(
            "generated/data.json not present yet "
            "(run the pipeline)"
        )
        return

    try:
        data = json.loads(
            data_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        fail(
            f"generated/data.json unreadable: {exc}"
        )
        return

    if not isinstance(
        data,
        dict,
    ):
        fail(
            "generated/data.json: root must be an object"
        )
        return

    required_top = {
        "meta",
        "snapshot",
        "security",
        "releases",
        "openSource",
        "history",
        "sources",
    }

    missing = (
        required_top
        - set(data.keys())
    )

    if missing:
        fail(
            "generated/data.json missing keys: "
            f"{sorted(missing)}"
        )
    else:
        print(
            "  data.json: all top-level "
            "sections present"
        )

    # -------------------------------------------------------------- #
    # Meta
    # -------------------------------------------------------------- #

    meta = data.get(
        "meta",
        {}
    )

    if not isinstance(
        meta,
        dict,
    ):
        fail(
            "generated/data.json: meta must be an object"
        )
        meta = {}

    meta_date = meta.get(
        "date"
    )

    if not is_valid_reporting_date(
        meta_date
    ):
        fail(
            "generated/data.json: "
            "meta.date must be a real YYYY-MM-DD date"
        )

    covered_date = meta.get(
        "coveredDate"
    )

    if (
        covered_date is not None
        and not is_valid_reporting_date(
            covered_date
        )
    ):
        fail(
            "generated/data.json: "
            "meta.coveredDate must be a real "
            "YYYY-MM-DD date"
        )

    generated_at = meta.get(
        "generatedAt"
    )

    if generated_at is not None:
        if not parse_iso_timestamp(
            generated_at
        ):
            fail(
                "generated/data.json: "
                "meta.generatedAt is not ISO-8601"
            )

    # -------------------------------------------------------------- #
    # Snapshot counts
    # -------------------------------------------------------------- #

    snapshot = data.get(
        "snapshot",
        {}
    )

    if not isinstance(
        snapshot,
        dict,
    ):
        fail(
            "generated/data.json: "
            "snapshot must be an object"
        )
        snapshot = {}

    for key in (
        "cves",
        "knownExploited",
        "releases",
        "projects",
        "techEntries",
    ):
        value = snapshot.get(
            key
        )

        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                int,
            )
            or value < 0
        ):
            fail(
                "generated/data.json: "
                f"snapshot.{key} must be a "
                "non-negative integer"
            )

    # -------------------------------------------------------------- #
    # Security records
    # -------------------------------------------------------------- #

    security = data.get(
        "security",
        {}
    )

    if not isinstance(
        security,
        dict,
    ):
        fail(
            "generated/data.json: "
            "security must be an object"
        )
        security = {}

    latest_cves = security.get(
        "latest",
        []
    )

    if not isinstance(
        latest_cves,
        list,
    ):
        fail(
            "generated/data.json: "
            "security.latest must be a list"
        )
        latest_cves = []

    seen_cves: set[str] = set()

    for cve in latest_cves:
        if not isinstance(
            cve,
            dict,
        ):
            fail(
                "generated/data.json: "
                "security.latest contains a "
                "non-object record"
            )
            continue

        cve_id = cve.get(
            "id",
            ""
        )

        if cve_id:
            if not (
                isinstance(
                    cve_id,
                    str,
                )
                and CVE_ID_PATTERN.fullmatch(
                    cve_id
                )
            ):
                fail(
                    "generated/data.json: "
                    f"malformed CVE id '{cve_id}'"
                )

            if cve_id in seen_cves:
                fail(
                    "generated/data.json: "
                    f"duplicate CVE '{cve_id}' "
                    "in security.latest"
                )

            seen_cves.add(
                cve_id
            )

        severity = cve.get(
            "severity"
        )

        if (
            severity is not None
            and severity
            not in (
                "CRITICAL",
                "HIGH",
                "MEDIUM",
                "LOW",
                "NONE",
            )
        ):
            fail(
                "generated/data.json: "
                f"invalid severity '{severity}' "
                f"on {cve_id}"
            )

        for stamp_field in (
            "publishedAt",
            "lastModifiedAt",
        ):
            value = cve.get(
                stamp_field
            )

            if value is not None and not parse_iso_timestamp(
                value
            ):
                fail(
                    "generated/data.json: "
                    f"{stamp_field} on {cve_id} "
                    "must be ISO-8601 or null"
                )

    # -------------------------------------------------------------- #
    # Relative-label protection
    # -------------------------------------------------------------- #

    for cve in latest_cves:
        for label_field in (
            "published",
            "modified",
        ):
            value = cve.get(
                label_field
            )

            if (
                isinstance(
                    value,
                    str,
                )
                and ISO_RELATIVE_LABEL_PATTERN.fullmatch(
                    value
                )
            ):
                fail(
                    "generated/data.json: frozen "
                    f"relative label in cve.{label_field} "
                    f"('{value}') — emit timestamps instead"
                )

    releases = data.get(
        "releases",
        []
    )

    if not isinstance(
        releases,
        list,
    ):
        fail(
            "generated/data.json: "
            "releases must be a list"
        )
        releases = []

    for release in releases:
        if not isinstance(
            release,
            dict,
        ):
            fail(
                "generated/data.json: "
                "releases contains a non-object record"
            )
            continue

        date = release.get(
            "date"
        )

        if (
            isinstance(
                date,
                str,
            )
            and ISO_RELATIVE_LABEL_PATTERN.fullmatch(
                date
            )
        ):
            fail(
                "generated/data.json: frozen "
                "relative label in release.date — "
                "emit publishedAt instead"
            )

        published_at = release.get(
            "publishedAt"
        )

        if (
            published_at is not None
            and not parse_iso_timestamp(
                published_at
            )
        ):
            fail(
                "generated/data.json: "
                "release.publishedAt must be ISO-8601"
            )

    technology = data.get(
        "technology",
        []
    )

    if not isinstance(
        technology,
        list,
    ):
        fail(
            "generated/data.json: "
            "technology must be a list"
        )
        technology = []

    for entry in technology:
        if not isinstance(
            entry,
            dict,
        ):
            fail(
                "generated/data.json: "
                "technology contains a non-object record"
            )
            continue

        date = entry.get(
            "date"
        )

        if (
            isinstance(
                date,
                str,
            )
            and ISO_RELATIVE_LABEL_PATTERN.fullmatch(
                date
            )
        ):
            fail(
                "generated/data.json: frozen "
                "relative label in technology.date — "
                "emit publishedAt instead"
            )

        published_at = entry.get(
            "publishedAt"
        )

        if (
            published_at is not None
            and not parse_iso_timestamp(
                published_at
            )
        ):
            fail(
                "generated/data.json: "
                "technology.publishedAt must be ISO-8601"
            )

    # -------------------------------------------------------------- #
    # Source health
    # -------------------------------------------------------------- #

    sources = data.get(
        "sources",
        {}
    )

    if not isinstance(
        sources,
        dict,
    ):
        fail(
            "generated/data.json: "
            "sources must be an object"
        )
    else:
        valid_statuses = {
            "success",
            "partial",
            "failed",
            "empty",
            "unknown",
        }

        for name, source in sources.items():
            if not isinstance(
                source,
                dict,
            ):
                fail(
                    "generated/data.json: "
                    f"sources.{name} must be an object"
                )
                continue

            status = source.get(
                "status"
            )

            if (
                status is not None
                and status not in valid_statuses
            ):
                fail(
                    "generated/data.json: "
                    f"sources.{name}.status has "
                    f"invalid value '{status}'"
                )

    print(
        f"  data.json: snapshot date "
        f"{meta.get('date')}"
    )

    # -------------------------------------------------------------- #
    # Archive
    # -------------------------------------------------------------- #

    archive_path = (
        PROJECT_ROOT
        / "generated"
        / "archive.json"
    )

    if archive_path.exists():
        try:
            archive = json.loads(
                archive_path.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(
                archive,
                dict,
            ):
                fail(
                    "generated/archive.json: "
                    "root must be an object"
                )
            elif not isinstance(
                archive.get("archive"),
                list,
            ):
                fail(
                    "generated/archive.json: "
                    "'archive' must be a list"
                )
            else:
                seen_dates: set[str] = set()

                for snapshot in archive[
                    "archive"
                ]:
                    if not isinstance(
                        snapshot,
                        dict,
                    ):
                        fail(
                            "generated/archive.json: "
                            "archive contains a "
                            "non-object record"
                        )
                        continue

                    date = snapshot.get(
                        "date"
                    )

                    if not is_valid_reporting_date(
                        date
                    ):
                        fail(
                            "generated/archive.json: "
                            f"invalid snapshot date "
                            f"'{date}'"
                        )
                        continue

                    if date in seen_dates:
                        fail(
                            "generated/archive.json: "
                            f"duplicate snapshot date "
                            f"'{date}'"
                        )

                    seen_dates.add(
                        date
                    )

                print(
                    "  archive.json: "
                    f"{len(archive['archive'])} snapshots"
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            fail(
                f"generated/archive.json unreadable: {exc}"
            )
    else:
        warn(
            "generated/archive.json not present yet"
        )


# ------------------------------------------------------------------ #
# 8. Raw data sanity
# ------------------------------------------------------------------ #

def validate_raw_file_metadata(
    path: Path,
    data: dict[str, Any],
    expected_source: str,
    records: list[Any],
) -> None:
    """Validate metadata that must agree with the snapshot filename."""

    relative = relative_path(path)
    filename_date = path.stem

    meta = data.get(
        "meta",
        {}
    )

    if not isinstance(
        meta,
        dict,
    ):
        fail(
            f"{relative}: meta must be an object"
        )
        return

    if not is_valid_reporting_date(
        filename_date
    ):
        fail(
            f"{relative}: filename must be "
            "a real YYYY-MM-DD date"
        )

    reporting_date = meta.get(
        "reportingDate"
    )

    if not is_valid_reporting_date(
        reporting_date
    ):
        fail(
            f"{relative}: meta.reportingDate "
            "must be a real YYYY-MM-DD date"
        )
    elif reporting_date != filename_date:
        fail(
            f"{relative}: meta.reportingDate "
            f"'{reporting_date}' does not match "
            f"filename date '{filename_date}'"
        )

    source = meta.get(
        "source"
    )

    if source != expected_source:
        fail(
            f"{relative}: meta.source must be "
            f"'{expected_source}'"
        )

    count = meta.get(
        "count"
    )

    if (
        isinstance(count, bool)
        or not isinstance(
            count,
            int,
        )
        or count < 0
    ):
        fail(
            f"{relative}: meta.count must be "
            "a non-negative integer"
        )
    elif count != len(records):
        fail(
            f"{relative}: meta.count ({count}) "
            f"!= record count ({len(records)})"
        )

    collected_at = meta.get(
        "collectedAt"
    )

    if not parse_iso_timestamp(
        collected_at
    ):
        fail(
            f"{relative}: meta.collectedAt "
            "must be ISO-8601"
        )

    if "failures" in meta:
        failures = meta.get(
            "failures"
        )

        if not isinstance(
            failures,
            list,
        ):
            fail(
                f"{relative}: meta.failures "
                "must be a list"
            )


def check_record_identity(
    path: Path,
    records: list[Any],
    id_of: Callable[
        [dict[str, Any]],
        Any,
    ],
    id_pattern: re.Pattern[str] | None,
) -> tuple[int, int]:
    """
    Validate record identity and return:
        (problems, unique_records)
    """

    problems = 0
    seen: set[Any] = set()

    for index, record in enumerate(
        records,
        start=1,
    ):
        if not isinstance(
            record,
            dict,
        ):
            fail(
                f"{relative_path(path)}: "
                f"record #{index} is not an object"
            )
            problems += 1
            continue

        try:
            record_id = id_of(
                record
            )
        except Exception:
            record_id = None

        if record_id is None:
            fail(
                f"{relative_path(path)}: "
                f"record #{index} has no usable identity"
            )
            problems += 1
            continue

        if isinstance(
            record_id,
            str,
        ):
            record_id = record_id.strip()

        if not record_id:
            fail(
                f"{relative_path(path)}: "
                f"record #{index} has an empty identity"
            )
            problems += 1
            continue

        if (
            id_pattern is not None
            and not id_pattern.fullmatch(
                str(record_id)
            )
        ):
            fail(
                f"{relative_path(path)}: "
                f"malformed id '{record_id}'"
            )
            problems += 1

        if record_id in seen:
            fail(
                f"{relative_path(path)}: "
                f"duplicate id '{record_id}' "
                "within snapshot"
            )
            problems += 1

        seen.add(
            record_id
        )

    return (
        problems,
        len(seen),
    )


def check_raw_data() -> None:
    section("8. Raw data sanity")

    # directory, list key, expected source, identity extractor, id pattern
    raw_specs: list[
        tuple[
            Path,
            str,
            str,
            Callable[[dict[str, Any]], Any],
            re.Pattern[str] | None,
        ]
    ] = [
        (
            PROJECT_ROOT
            / "data"
            / "security"
            / "nvd",
            "vulnerabilities",
            "NVD",
            lambda record: record.get("id"),
            CVE_ID_PATTERN,
        ),
        (
            PROJECT_ROOT
            / "data"
            / "security"
            / "cisa",
            "vulnerabilities",
            "CISA KEV",
            lambda record: record.get("cve_id"),
            CVE_ID_PATTERN,
        ),
        (
            PROJECT_ROOT
            / "data"
            / "releases",
            "releases",
            "GitHub",
            lambda record: (
                f"{record.get('repository')}"
                f"@{record.get('version')}"
            ),
            None,
        ),
        (
            PROJECT_ROOT
            / "data"
            / "opensource",
            "repositories",
            "GitHub",
            lambda record: record.get(
                "full_name"
            ),
            None,
        ),
        (
            PROJECT_ROOT
            / "data"
            / "tech",
            "entries",
            "RSS",
            lambda record: (
                record.get("guid")
                or record.get("url")
                or record.get("title")
            ),
            None,
        ),
    ]

    checked_any = False

    for (
        directory,
        list_key,
        expected_source,
        id_of,
        id_pattern,
    ) in raw_specs:
        if not directory.exists():
            continue

        files = sorted(
            directory.glob(
                "*.json"
            )
        )

        if not files:
            continue

        checked_any = True
        problems = 0
        total_records = 0
        unique_total: set[Any] = set()

        for path in files:
            try:
                data = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ) as exc:
                fail(
                    f"Raw file unreadable "
                    f"{relative_path(path)}: {exc}"
                )
                problems += 1
                continue

            if not isinstance(
                data,
                dict,
            ):
                fail(
                    f"{relative_path(path)}: "
                    "root must be an object"
                )
                problems += 1
                continue

            records = data.get(
                list_key
            )

            if not isinstance(
                records,
                list,
            ):
                fail(
                    f"{relative_path(path)}: "
                    f"'{list_key}' must be a list"
                )
                problems += 1
                continue

            validate_raw_file_metadata(
                path,
                data,
                expected_source,
                records,
            )

            total_records += len(
                records
            )

            file_problems, unique_count = (
                check_record_identity(
                    path,
                    records,
                    id_of,
                    id_pattern,
                )
            )

            problems += file_problems

            # Reconstruct the unique set for summary output.
            for record in records:
                if not isinstance(
                    record,
                    dict,
                ):
                    continue

                try:
                    record_id = id_of(
                        record
                    )
                except Exception:
                    continue

                if isinstance(
                    record_id,
                    str,
                ):
                    record_id = record_id.strip()

                if record_id:
                    unique_total.add(
                        record_id
                    )

            # Source-specific timestamp sanity.
            for record in records:
                if not isinstance(
                    record,
                    dict,
                ):
                    continue

                if expected_source == "NVD":
                    for field in (
                        "published",
                        "lastModified",
                    ):
                        value = record.get(
                            field
                        )

                        if (
                            value is not None
                            and not parse_iso_timestamp(
                                value
                            )
                        ):
                            fail(
                                f"{relative_path(path)}: "
                                f"{field} must be ISO-8601 "
                                "or null"
                            )

                elif expected_source == "CISA KEV":
                    for field in (
                        "date_added",
                        "due_date",
                    ):
                        value = record.get(
                            field
                        )

                        if value is not None and not (
                            isinstance(
                                value,
                                str,
                            )
                            and value.strip()
                        ):
                            fail(
                                f"{relative_path(path)}: "
                                f"{field} must be a "
                                "non-empty string or null"
                            )

                elif expected_source == "GitHub":
                    # GitHub uses both repository and release snapshots.
                    for field in (
                        "created_at",
                        "updated_at",
                        "pushed_at",
                        "published_at",
                    ):
                        if field in record:
                            value = record.get(
                                field
                            )

                            if (
                                value is not None
                                and not parse_iso_timestamp(
                                    value
                                )
                            ):
                                fail(
                                    f"{relative_path(path)}: "
                                    f"{field} must be "
                                    "ISO-8601 or null"
                                )

                elif expected_source == "RSS":
                    for field in (
                        "published_at",
                        "observed_at",
                    ):
                        if field in record:
                            value = record.get(
                                field
                            )

                            if (
                                value is not None
                                and not parse_iso_timestamp(
                                    value
                                )
                            ):
                                fail(
                                    f"{relative_path(path)}: "
                                    f"{field} must be "
                                    "ISO-8601 or null"
                                )

        label = relative_path(
            directory
        )

        print(
            f"  {label}: "
            f"{len(files)} file(s), "
            f"{total_records} records, "
            f"{len(unique_total)} unique identities, "
            f"{problems} problems"
        )

    if not checked_any:
        print(
            "  No raw data collected yet "
            "(this is fine before first run)"
        )


# ------------------------------------------------------------------ #
# 9. Cross-snapshot integrity
# ------------------------------------------------------------------ #

def check_raw_snapshot_sequence() -> None:
    """
    Ensure raw dated snapshots use valid dates and do not contain
    duplicate filenames/dates.

    Missing dates are intentionally NOT treated as failures because
    legitimate collection gaps can occur and are represented by source
    health data.
    """

    section("9. Raw snapshot consistency")

    directories = [
        PROJECT_ROOT / "data" / "security" / "nvd",
        PROJECT_ROOT / "data" / "security" / "cisa",
        PROJECT_ROOT / "data" / "opensource",
        PROJECT_ROOT / "data" / "releases",
        PROJECT_ROOT / "data" / "tech",
        PROJECT_ROOT / "data" / "daily",
    ]

    checked = 0

    for directory in directories:
        if not directory.exists():
            continue

        files = sorted(
            directory.glob("*.json")
        )

        if not files:
            continue

        checked += 1

        for path in files:
            if not is_valid_reporting_date(
                path.stem
            ):
                fail(
                    f"{relative_path(path)}: "
                    "snapshot filename must be "
                    "YYYY-MM-DD"
                )

    if checked:
        print(
            f"  {checked} snapshot directories checked"
        )
    else:
        print(
            "  No dated snapshot directories "
            "available yet"
        )


def main() -> int:
    reset_results()

    print("=" * 50)
    print("TechPulse — Offline Validation")
    print("=" * 50)

    check_python_syntax()
    check_json_validity()
    check_structure()
    check_configs()
    check_frontend()
    check_placeholders()
    check_generated_data()
    check_raw_data()
    check_raw_snapshot_sequence()

    print()
    print("=" * 50)

    if WARNINGS:
        print(
            f"Warnings ({len(WARNINGS)}):"
        )

        for warning in WARNINGS:
            print(
                f"  ! {warning}"
            )

    if FAILURES:
        print(
            f"VALIDATION FAILED "
            f"({len(FAILURES)} issue(s)):"
        )

        for failure in FAILURES:
            print(
                f"  x {failure}"
            )

        return 1

    print(
        "VALIDATION PASSED ✓"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
