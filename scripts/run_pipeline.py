#!/usr/bin/env python3

"""
TechPulse — Pipeline Runner

Executes the complete data collection and generation pipeline.

Usage:
    python3 scripts/run_pipeline.py [--date YYYY-MM-DD] [--skip-collect] [--skip-process] [--skip-generate]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

COLLECTORS = [
    ("NVD", "scripts/sources/nvd/collect.py", True, 300),      # supports window args - 5 min timeout
    ("CISA KEV", "scripts/sources/cisa/collect.py", False, 60), # no args
    ("GitHub", "scripts/sources/github/collect.py", False, 600),  # no args (uses config) - 10 min timeout
    ("RSS/Atom", "scripts/sources/rss/collect.py", False, 300),  # no args (uses config)
]

PROCESSORS = [
    ("Security", "scripts/processors/security.py", True),
    ("Releases", "scripts/processors/releases.py", True),
    ("Open Source", "scripts/processors/opensource.py", True),
    ("Technology", "scripts/processors/tech.py", True),
    ("Daily Snapshot", "scripts/processors/daily.py", False), # uses --date
    ("History", "scripts/processors/history.py", False),      # no args
]

GENERATORS = [
    ("Site Data", "scripts/generators/site_data.py", False),
    ("Archive", "scripts/generators/archive.py", False),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_script(script_path: str, args: list[str] = None, timeout: int = 300) -> tuple[bool, str]:
    """Run a Python script and return (success, output)."""
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: {script_path} exceeded {timeout} seconds"
    except Exception as exc:
        return False, f"ERROR: {exc}"


def print_stage(name: str, success: bool, output: str = "") -> None:
    """Print stage result."""
    status = "✓" if success else "✗"
    print(f"  [{status}] {name}")
    if output and not success:
        for line in output.strip().split("\n")[-5:]:  # Last 5 lines
            print(f"      {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TechPulse data pipeline.")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD), defaults to previous UTC day")
    parser.add_argument("--skip-collect", action="store_true", help="Skip source collection")
    parser.add_argument("--skip-process", action="store_true", help="Skip data processing")
    parser.add_argument("--skip-generate", action="store_true", help="Skip data generation")
    parser.add_argument("--only", choices=["collect", "process", "generate"], help="Run only one phase")
    args = parser.parse_args()

    # Determine snapshot date
    if args.date:
        try:
            snapshot_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: Invalid date format: {args.date}. Use YYYY-MM-DD")
            return 1
    else:
        snapshot_date = utc_now() - timedelta(days=1)
        snapshot_date = snapshot_date.replace(hour=0, minute=0, second=0, microsecond=0)

    window_start = snapshot_date.isoformat()
    window_end = (snapshot_date + timedelta(days=1) - timedelta(seconds=1)).isoformat()

    processor_args = ["--start", window_start, "--end", window_end]
    daily_args = ["--date", snapshot_date.date().isoformat()]

    print()
    print("TechPulse — Pipeline Runner")
    print("=" * 50)
    print(f"Snapshot date: {snapshot_date.date().isoformat()}")
    print(f"Window: {window_start} to {window_end}")
    print()

    overall_success = True

    # Phase 1: Collect
    if not args.skip_collect and args.only != "process" and args.only != "generate":
        print("Phase 1: Source Collection")
        print("-" * 30)
        for name, script, uses_window, timeout in COLLECTORS:
            start = time.time()
            if uses_window:
                success, output = run_script(script, processor_args, timeout)
            else:
                success, output = run_script(script, timeout=timeout)
            elapsed = time.time() - start
            print_stage(f"{name} ({elapsed:.1f}s)", success, output)
            if not success:
                overall_success = False
        print()

    # Phase 2: Process
    if not args.skip_process and args.only != "collect" and args.only != "generate":
        print("Phase 2: Data Processing")
        print("-" * 30)
        for name, script, uses_window in PROCESSORS:
            start = time.time()
            if name == "Daily Snapshot":
                success, output = run_script(script, daily_args)
            elif name == "History":
                success, output = run_script(script)
            elif uses_window:
                success, output = run_script(script, processor_args)
            else:
                success, output = run_script(script)
            elapsed = time.time() - start
            print_stage(f"{name} ({elapsed:.1f}s)", success, output)
            if not success:
                overall_success = False
        print()

    # Phase 3: Generate
    if not args.skip_generate and args.only != "collect" and args.only != "process":
        print("Phase 3: Data Generation")
        print("-" * 30)
        for name, script, uses_window in GENERATORS:
            start = time.time()
            success, output = run_script(script)
            elapsed = time.time() - start
            print_stage(f"{name} ({elapsed:.1f}s)", success, output)
            if not success:
                overall_success = False
        print()

    # Summary
    print("=" * 50)
    if overall_success:
        print("Pipeline completed successfully ✓")
        return 0
    else:
        print("Pipeline completed with errors ✗")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())