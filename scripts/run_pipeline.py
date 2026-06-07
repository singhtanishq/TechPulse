#!/usr/bin/env python3

"""
TechPulse — Pipeline Runner

Executes the complete data pipeline for one snapshot date:
collect -> process -> generate -> validate.

Usage:
    python3 scripts/run_pipeline.py [--date YYYY-MM-DD] [--skip-collect]
        [--skip-process] [--skip-generate] [--only collect|process|generate]

Exit codes:
    0 — pipeline completed (partial source failures are reported in
        logs and the source health data, but do not fail the run)
    1 — fatal: invalid arguments, a processing/generation stage failed,
        or every collector failed (no usable data at all)

Snapshot semantics:
    Default snapshot date is the previous completed UTC day, matching
    scripts/config/snapshot.json.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (name, script, accepts --date flag, timeout seconds)
COLLECTORS = [
    ("NVD", "scripts/sources/nvd/collect.py", True, 600),
    ("CISA KEV", "scripts/sources/cisa/collect.py", True, 120),
    ("GitHub", "scripts/sources/github/collect.py", True, 600),
    ("RSS/Atom", "scripts/sources/rss/collect.py", True, 300),
]

PROCESSORS = [
    ("Security", "scripts/processors/security.py", True, 60),
    ("Releases", "scripts/processors/releases.py", True, 60),
    ("Open Source", "scripts/processors/opensource.py", True, 60),
    ("Technology", "scripts/processors/tech.py", True, 60),
    ("Daily Snapshot", "scripts/processors/daily.py", True, 60),
    ("History", "scripts/processors/history.py", False, 60),
]

GENERATORS = [
    ("Site Data", "scripts/generators/site_data.py", True, 60),
    ("Archive", "scripts/generators/archive.py", False, 60),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_snapshot_date() -> datetime:
    day = (utc_now() - timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def run_script(script: str, args: list[str], timeout: int) -> tuple[bool, str]:
    """Run one pipeline script. Returns (success, combined output)."""

    cmd = [sys.executable, script, *args]

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout or ""
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: {script} exceeded {timeout}s"
    except Exception as exc:
        return False, f"ERROR: {exc}"


def print_stage(name: str, success: bool, output: str, verbose: bool) -> bool:
    """Print a stage result line. Returns True when output warrants attention."""
    marker = "✓" if success else "✗"
    print(f"  [{marker}] {name}")
    interesting = []
    for line in output.splitlines():
        lowered = line.lower()
        if (
            not success
            or lowered.startswith(("error", "warning", "failures", "timeout"))
            or "error:" in lowered
            or "warning:" in lowered
        ):
            interesting.append(line)
    for line in interesting[:6]:
        print(f"      {line}")
    if verbose and output:
        for line in output.splitlines():
            print(f"      | {line}")
    return bool(interesting)


def main() -> int:

    parser = argparse.ArgumentParser(description="Run the TechPulse data pipeline.")
    parser.add_argument(
        "--date",
        help="Snapshot date (YYYY-MM-DD, UTC). Default: previous completed UTC day.",
    )
    parser.add_argument("--skip-collect", action="store_true", help="Skip source collection.")
    parser.add_argument("--skip-process", action="store_true", help="Skip processing.")
    parser.add_argument("--skip-generate", action="store_true", help="Skip generation.")
    parser.add_argument(
        "--only",
        choices=["collect", "process", "generate"],
        help="Run only one phase.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print all stage output.")
    args = parser.parse_args()

    if args.date:
        try:
            snapshot_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: Invalid date '{args.date}'. Use YYYY-MM-DD.", file=sys.stderr)
            return 1
    else:
        snapshot_date = default_snapshot_date()

    date_str = snapshot_date.date().isoformat()

    print()
    print("TechPulse — Pipeline Runner")
    print("=" * 50)
    print(f"Snapshot date : {date_str} (UTC calendar day)")
    print()

    overall_success = True
    collector_failures = 0
    collector_total = 0
    run_collect = not args.skip_collect and args.only in (None, "collect")
    run_process = not args.skip_process and args.only in (None, "process")
    run_generate = not args.skip_generate and args.only in (None, "generate")

    # Phase 1: Collect --------------------------------------------------
    if run_collect:
        print("Phase 1: Source Collection")
        print("-" * 30)
        for name, script, takes_date, timeout in COLLECTORS:
            stage_args = ["--date", date_str] if takes_date else []
            start = time.time()
            success, output = run_script(script, stage_args, timeout)
            elapsed = time.time() - start
            collector_total += 1
            if not success:
                collector_failures += 1
                overall_success = False
            print_stage(f"{name} ({elapsed:.1f}s)", success, output, args.verbose)
        print()

    # Phase 2: Process --------------------------------------------------
    if run_process:
        print("Phase 2: Data Processing")
        print("-" * 30)
        for name, script, takes_date, timeout in PROCESSORS:
            stage_args = ["--date", date_str] if takes_date else []
            start = time.time()
            success, output = run_script(script, stage_args, timeout)
            elapsed = time.time() - start
            if not success:
                overall_success = False
            print_stage(f"{name} ({elapsed:.1f}s)", success, output, args.verbose)
        print()

    # Phase 3: Generate -------------------------------------------------
    if run_generate:
        print("Phase 3: Data Generation")
        print("-" * 30)
        for name, script, takes_date, timeout in GENERATORS:
            stage_args = ["--date", date_str] if takes_date else []
            start = time.time()
            success, output = run_script(script, stage_args, timeout)
            elapsed = time.time() - start
            if not success:
                overall_success = False
            print_stage(f"{name} ({elapsed:.1f}s)", success, output, args.verbose)
        print()

    # Summary -----------------------------------------------------------
    print("=" * 50)
    if collector_failures:
        print(
            f"Source health: {collector_total - collector_failures}/{collector_total} "
            "collectors succeeded (see per-stage output above)."
        )

    if overall_success:
        print(f"Pipeline completed successfully ✓  (snapshot {date_str})")
        return 0

    # A collector failure is fatal only when every collector failed:
    # partial availability is a designed, honest outcome.
    if run_collect and collector_failures == collector_total and collector_total > 0:
        print("Pipeline failed: every collector failed; no usable data collected. ✗",
              file=sys.stderr)
        return 1

    print("Pipeline completed with failures ✗", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
