#!/usr/bin/env python3

"""
TechPulse — Offline Validator

Performs full offline repository validation. Never touches the network.

Checks:
    1. Python syntax (every tracked .py file compiles)
    2. JSON validity (every .json file parses)
    3. Expected directory structure
    4. Configuration files present and structurally sane
    5. Frontend files present; JS references resolve to files/DOM hooks
    6. Placeholder / fake-data detection
    7. Generated data schema sanity (when generated files exist)
    8. Raw data schema sanity (when raw files exist)

Run:
    python3 scripts/validate.py

Exit codes:
    0 — all checks passed (or no generated data exists yet)
    1 — one or more checks failed
"""

from __future__ import annotations

import json
import py_compile
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FAILURES: list[str] = []
WARNINGS: list[str] = []


def fail(message: str) -> None:
    FAILURES.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# ------------------------------------------------------------------ #
# 1. Python syntax
# ------------------------------------------------------------------ #

def check_python_syntax() -> None:
    section("1. Python syntax")
    py_files = sorted(
        p for p in PROJECT_ROOT.rglob("*.py")
        if ".git" not in p.parts and "__pycache__" not in p.parts
    )
    if not py_files:
        fail("No Python files found")
        return
    errors = 0
    for path in py_files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            fail(f"Syntax error in {path.relative_to(PROJECT_ROOT)}: {exc}")
            errors += 1
    status = "OK" if errors == 0 else "FAILED"
    print(f"  {len(py_files)} files checked: {status}")


# ------------------------------------------------------------------ #
# 2. JSON validity
# ------------------------------------------------------------------ #

def check_json_validity() -> None:
    section("2. JSON validity")
    json_files = sorted(
        p for p in PROJECT_ROOT.rglob("*.json")
        if ".git" not in p.parts and "__pycache__" not in p.parts
    )
    if not json_files:
        warn("No JSON files found")
        return
    errors = 0
    for path in json_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            fail(f"Invalid JSON in {path.relative_to(PROJECT_ROOT)}: {exc}")
            errors += 1
    status = "OK" if errors == 0 else "FAILED"
    print(f"  {len(json_files)} files checked: {status}")


# ------------------------------------------------------------------ #
# 3. Expected structure
# ------------------------------------------------------------------ #

EXPECTED_PATHS = [
    "scripts/run_pipeline.py",
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
    "src/js/app.js",
    "src/js/components.js",
    "src/css/base.css",
    "src/css/layout.css",
    "src/css/components.css",
    ".github/workflows",
    "README.md",
    "LICENSE",
]


def check_structure() -> None:
    section("3. Expected structure")
    missing = [p for p in EXPECTED_PATHS if not (PROJECT_ROOT / p).exists()]
    if missing:
        for path in missing:
            fail(f"Missing expected path: {path}")
    print(f"  {len(EXPECTED_PATHS) - len(missing)}/{len(EXPECTED_PATHS)} present")


# ------------------------------------------------------------------ #
# 4. Configuration sanity
# ------------------------------------------------------------------ #

def check_configs() -> None:
    section("4. Configuration sanity")

    github_config = PROJECT_ROOT / "scripts" / "config" / "github.json"
    try:
        data = json.loads(github_config.read_text(encoding="utf-8"))
        repos = data.get("tracked_repositories", [])
        valid = all(
            isinstance(r, dict) and r.get("owner") and r.get("repo")
            for r in repos
        )
        if not repos:
            fail("github.json: no tracked repositories configured")
        elif not valid:
            fail("github.json: tracked_repositories entries need owner and repo")
        else:
            print(f"  github.json: {len(repos)} tracked repositories OK")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"github.json unreadable: {exc}")

    rss_config = PROJECT_ROOT / "scripts" / "config" / "rss.json"
    try:
        data = json.loads(rss_config.read_text(encoding="utf-8"))
        feeds = data.get("feeds", [])
        bad = [f for f in feeds if not f.get("url")]
        if not feeds:
            fail("rss.json: no feeds configured")
        elif bad:
            fail(f"rss.json: {len(bad)} feeds missing url")
        else:
            print(f"  rss.json: {len(feeds)} feeds OK")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"rss.json unreadable: {exc}")

    snapshot_config = PROJECT_ROOT / "scripts" / "config" / "snapshot.json"
    try:
        data = json.loads(snapshot_config.read_text(encoding="utf-8"))
        model = (data.get("snapshot") or {}).get("model")
        if model != "utc_calendar_day":
            fail("snapshot.json: snapshot.model must be utc_calendar_day")
        else:
            print("  snapshot.json: utc_calendar_day model OK")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"snapshot.json unreadable: {exc}")


# ------------------------------------------------------------------ #
# 5. Frontend wiring
# ------------------------------------------------------------------ #

def check_frontend() -> None:
    section("5. Frontend wiring")

    pages = ["index.html", "security.html", "releases.html", "opensource.html", "history.html"]
    for page in pages:
        path = PROJECT_ROOT / "src" / page
        try:
            html = path.read_text(encoding="utf-8")
        except OSError as exc:
            fail(f"{page} unreadable: {exc}")
            continue

        for script in ("js/data.js", "js/components.js", "js/app.js"):
            if script not in html:
                fail(f"{page}: missing script reference {script}")

        for css in ("css/base.css", "css/layout.css", "css/components.css"):
            if css not in html:
                fail(f"{page}: missing stylesheet reference {css}")

        if 'href="' in html:
            internal = re.findall(r'href="([a-z0-9\-]+\.html)"', html)
            for link in internal:
                if not (PROJECT_ROOT / "src" / link).exists():
                    fail(f"{page}: broken internal link -> {link}")

        title = re.search(r"<title>(.*?)</title>", html)
        if not title or not title.group(1).strip():
            fail(f"{page}: missing title")

    # Brand consistency.
    for page in pages:
        html = (PROJECT_ROOT / "src" / page).read_text(encoding="utf-8")
        if 'brand-mark">TP<' in html:
            fail(f"{page}: inconsistent brand mark 'TP' (expected 'T')")

    print(f"  {len(pages)} pages checked")


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

PLACEHOLDER_SCAN_FILES = ["*.html", "*.js", "*.css", "*.py", "*.json", "*.md"]


def check_placeholders() -> None:
    section("6. Placeholder detection")
    findings = 0
    self_path = Path(__file__).resolve()
    for pattern_name in PROJECT_ROOT.rglob("*"):
        if ".git" in pattern_name.parts or "__pycache__" in pattern_name.parts:
            continue
        if not pattern_name.is_file():
            continue
        if pattern_name.resolve() == self_path:
            continue  # The detector itself legitimately contains the patterns.
        if pattern_name.suffix not in (".html", ".js", ".css", ".py", ".json", ".md"):
            continue
        try:
            content = pattern_name.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern.lower() in content.lower():
                rel = pattern_name.relative_to(PROJECT_ROOT)
                fail(f"Placeholder '{pattern}' found in {rel}")
                findings += 1
    if findings == 0:
        print("  No placeholder content found")


# ------------------------------------------------------------------ #
# 7. Generated data schema
# ------------------------------------------------------------------ #

def check_generated_data() -> None:
    section("7. Generated data schema")

    data_path = PROJECT_ROOT / "generated" / "data.json"
    if not data_path.exists():
        warn("generated/data.json not present yet (run the pipeline)")
        return

    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"generated/data.json unreadable: {exc}")
        return

    required_top = {"meta", "snapshot", "security", "releases", "openSource", "history", "sources"}
    missing = required_top - set(data.keys())
    if missing:
        fail(f"generated/data.json missing keys: {sorted(missing)}")
    else:
        print("  data.json: all top-level sections present")

    meta = data.get("meta", {})
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta.get("date", ""))):
        fail("generated/data.json: meta.date must be YYYY-MM-DD")

    snapshot = data.get("snapshot", {})
    for key in ("cves", "knownExploited", "releases", "projects", "techEntries"):
        value = snapshot.get(key)
        if not isinstance(value, int) or value < 0:
            fail(f"generated/data.json: snapshot.{key} must be a non-negative integer")

    # CVEs must be real-looking IDs.
    for cve in data.get("security", {}).get("latest", []):
        cve_id = cve.get("id", "")
        if cve_id and not re.match(r"^CVE-\d{4}-\d{4,}$", cve_id):
            fail(f"generated/data.json: malformed CVE id '{cve_id}'")
        severity = cve.get("severity")
        if severity is not None and severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"):
            fail(f"generated/data.json: invalid severity '{severity}' on {cve_id}")

    # Timestamps must parse.
    for field in ("generatedAt",):
        value = meta.get(field)
        if value:
            try:
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                fail(f"generated/data.json: meta.{field} not ISO-8601")

    print(f"  data.json: snapshot date {meta.get('date')}")

    archive_path = PROJECT_ROOT / "generated" / "archive.json"
    if archive_path.exists():
        try:
            archive = json.loads(archive_path.read_text(encoding="utf-8"))
            if not isinstance(archive.get("archive"), list):
                fail("generated/archive.json: 'archive' must be a list")
            else:
                print(f"  archive.json: {len(archive['archive'])} snapshots")
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"generated/archive.json unreadable: {exc}")
    else:
        warn("generated/archive.json not present yet")


# ------------------------------------------------------------------ #
# 8. Raw data sanity
# ------------------------------------------------------------------ #

def check_raw_data() -> None:
    section("8. Raw data sanity")

    raw_specs = [
        (PROJECT_ROOT / "data" / "security" / "nvd", "vulnerabilities", "id", r"^CVE-\d{4}-\d{4,}$"),
        (PROJECT_ROOT / "data" / "security" / "cisa", "vulnerabilities", "cve_id", r"^CVE-\d{4}-\d{4,}$"),
        (PROJECT_ROOT / "data" / "releases", "releases", "repository", None),
        (PROJECT_ROOT / "data" / "opensource", "repositories", "full_name", None),
        (PROJECT_ROOT / "data" / "tech", "entries", "guid", None),
    ]

    checked_any = False
    for directory, list_key, id_key, id_pattern in raw_specs:
        if not directory.exists():
            continue
        files = sorted(directory.glob("*.json"))
        if not files:
            continue
        checked_any = True
        problems = 0
        seen: set = set()
        duplicates = 0
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                fail(f"Raw file unreadable {path.relative_to(PROJECT_ROOT)}: {exc}")
                problems += 1
                continue
            records = data.get(list_key, [])
            count = (data.get("meta") or {}).get("count")
            if isinstance(count, int) and count != len(records):
                warn(f"{path.name}: meta.count ({count}) != record count ({len(records)})")
            for record in records:
                if not isinstance(record, dict):
                    problems += 1
                    continue
                record_id = record.get(id_key)
                if record_id is None:
                    problems += 1
                    continue
                if id_pattern and not re.match(id_pattern, str(record_id)):
                    fail(f"{path.name}: malformed id '{record_id}'")
                    problems += 1
                if record_id in seen:
                    duplicates += 1
                seen.add(record_id)
        label = directory.relative_to(PROJECT_ROOT)
        dup_note = f", {duplicates} duplicate ids" if duplicates else ""
        print(f"  {label}: {len(files)} file(s), {len(seen)} unique records, "
              f"{problems} problems{dup_note}")
        if duplicates:
            warn(f"{label}: duplicate ids present")

    if not checked_any:
        print("  No raw data collected yet (this is fine before first run)")


def main() -> int:
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

    print()
    print("=" * 50)

    if WARNINGS:
        print(f"Warnings ({len(WARNINGS)}):")
        for warning in WARNINGS:
            print(f"  ! {warning}")

    if FAILURES:
        print(f"VALIDATION FAILED ({len(FAILURES)} issue(s)):")
        for failure in FAILURES:
            print(f"  x {failure}")
        return 1

    print("VALIDATION PASSED ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
