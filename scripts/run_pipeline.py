#!/usr/bin/env python3

"""
TechPulse — Pipeline Runner

Executes the complete data pipeline for one reporting date:
collect -> process -> generate.

Usage:
    python3 scripts/run_pipeline.py [--date YYYY-MM-DD]
        [--catch-up] [--skip-collect] [--skip-process] [--skip-generate]
        [--only collect|process|generate]

Exit codes:
    0 — requested pipeline stages completed successfully.
        Partial collector failures are recorded in source-health data
        and do not fail the run when at least one collector succeeds.
        In --catch-up mode, at least one edition completed (a later
        failed edition is reported and retried on the next run).

    1 — fatal:
        invalid arguments,
        a processing/generation stage failed,
        every requested collector failed,
        no pipeline stage was actually selected, or
        (without --catch-up) the single requested edition failed.

Reporting semantics:
    TechPulse reporting dates are India calendar days
    (Asia/Kolkata).

    The edition for date X covers the previous IST day (X-1).
    The daily workflow fires at 18:30 UTC = 00:00 IST, at the
    start of day X.

    Default resolution (no --date):
    next pending edition after the newest valid snapshot,
    never later than the current IST date.

    --catch-up keeps resolving and processing further pending editions
    (bounded by MAX_EDITIONS_PER_RUN) until the archive has caught up
    with the current IST date. This heals backlogs left by failed runs
    within a single scheduled execution instead of advancing one day
    per day.

    See scripts/processors/utils.py for the shared resolver.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    ist_day_window,
    ist_now,
    parse_ist_date,
    resolve_reporting_date,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# (name, script, accepts --date flag, timeout seconds)
COLLECTORS = [
    (
        "NVD",
        "scripts/sources/nvd/collect.py",
        True,
        600,
    ),
    (
        "CISA KEV",
        "scripts/sources/cisa/collect.py",
        True,
        120,
    ),
    (
        "GitHub",
        "scripts/sources/github/collect.py",
        True,
        600,
    ),
    (
        "RSS/Atom",
        "scripts/sources/rss/collect.py",
        True,
        300,
    ),
]

PROCESSORS = [
    (
        "Security",
        "scripts/processors/security.py",
        True,
        60,
    ),
    (
        "Releases",
        "scripts/processors/releases.py",
        True,
        60,
    ),
    (
        "Open Source",
        "scripts/processors/opensource.py",
        True,
        60,
    ),
    (
        "Technology",
        "scripts/processors/tech.py",
        True,
        60,
    ),
    (
        "Daily Snapshot",
        "scripts/processors/daily.py",
        True,
        60,
    ),
    (
        "History",
        "scripts/processors/history.py",
        False,
        60,
    ),
]

GENERATORS = [
    (
        "Site Data",
        "scripts/generators/site_data.py",
        True,
        60,
    ),
    (
        "Archive",
        "scripts/generators/archive.py",
        False,
        60,
    ),
]

# Upper bound on editions processed in a single pipeline invocation.
# A backlog (caused by previously failed runs) is healed across
# consecutive runs: each run processes up to this many editions, so
# even multi-week gaps catch up without unbounded runtimes.
MAX_EDITIONS_PER_RUN = 8


def run_script(
    script: str,
    args: list[str],
    timeout: int,
) -> tuple[bool, str]:
    """
    Run one pipeline script.

    Returns:
        (success, combined_output)

    The child process inherits the current environment, including
    GITHUB_TOKEN / GH_TOKEN when present.
    """

    script_path = PROJECT_ROOT / script

    if not script_path.is_file():
        return (
            False,
            f"ERROR: Pipeline script does not exist: {script}",
        )

    if timeout <= 0:
        return (
            False,
            f"ERROR: Invalid timeout configured for {script}: {timeout}",
        )

    cmd = [
        sys.executable,
        str(script_path),
        *args,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    except subprocess.TimeoutExpired as exc:
        output_parts: list[str] = []

        if exc.stdout:
            output_parts.append(
                exc.stdout
                if isinstance(exc.stdout, str)
                else exc.stdout.decode(
                    errors="replace"
                )
            )

        if exc.stderr:
            output_parts.append(
                exc.stderr
                if isinstance(exc.stderr, str)
                else exc.stderr.decode(
                    errors="replace"
                )
            )

        output = "\n".join(
            part.rstrip()
            for part in output_parts
            if part
        )

        message = (
            f"TIMEOUT: {script} exceeded {timeout}s"
        )

        if output:
            message = f"{message}\n{output}"

        return False, message

    except OSError as exc:
        return (
            False,
            f"ERROR: Could not execute {script}: {exc}",
        )

    except Exception as exc:
        return (
            False,
            f"ERROR: {exc}",
        )

    output = result.stdout or ""

    if result.stderr:
        output += (
            "\n" if output else ""
        ) + result.stderr

    if result.returncode != 0:
        output = (
            f"{output.rstrip()}\n"
            f"EXIT CODE: {result.returncode}"
        ).strip()

    return (
        result.returncode == 0,
        output,
    )


def print_stage(
    name: str,
    success: bool,
    output: str,
    verbose: bool,
) -> bool:
    """
    Print a stage result line.

    Returns True when output contains information that warrants
    attention.
    """

    marker = "✓" if success else "✗"

    print(
        f"  [{marker}] {name}"
    )

    interesting: list[str] = []

    for line in output.splitlines():
        lowered = line.lower().strip()

        if (
            not success
            or lowered.startswith(
                (
                    "error",
                    "warning",
                    "failures",
                    "timeout",
                    "failed",
                )
            )
            or "error:" in lowered
            or "warning:" in lowered
            or "failed:" in lowered
            or "rate limit" in lowered
        ):
            interesting.append(line)

    for line in interesting[:8]:
        print(
            f"      {line}"
        )

    if verbose and output:
        for line in output.splitlines():
            print(
                f"      | {line}"
            )

    return bool(interesting)


def validate_arguments(
    args: argparse.Namespace,
) -> str | None:
    """
    Validate interactions between --only, --skip-* and --catch-up
    options.

    Returns an error string or None when the argument combination is
    valid.
    """

    skip_flags = {
        "collect": args.skip_collect,
        "process": args.skip_process,
        "generate": args.skip_generate,
    }

    if args.catch_up:
        if args.only:
            return (
                "--catch-up cannot be combined with --only: catch-up "
                "requires the full pipeline for each edition."
            )

        if any(skip_flags.values()):
            return (
                "--catch-up cannot be combined with --skip-* flags: "
                "catch-up requires the full pipeline for each edition."
            )

    if args.only:
        if skip_flags.get(args.only):
            return (
                f"--only {args.only} cannot be combined with "
                f"--skip-{args.only}."
            )

        conflicting = [
            phase
            for phase, skipped in skip_flags.items()
            if phase != args.only and skipped
        ]

        if conflicting:
            return (
                "--only cannot be combined with skip flags for "
                f"other phases: {', '.join(conflicting)}."
            )

    if (
        args.only is None
        and args.skip_collect
        and args.skip_process
        and args.skip_generate
    ):
        return (
            "All pipeline phases are skipped; "
            "there is nothing to run."
        )

    if args.date:
        try:
            parse_ist_date(args.date)
        except (TypeError, ValueError):
            return (
                "Reporting date must be YYYY-MM-DD."
            )

    return None


def selected_phases(
    args: argparse.Namespace,
) -> tuple[bool, bool, bool]:
    """Return whether collection, processing and generation run."""

    if args.only == "collect":
        return True, False, False

    if args.only == "process":
        return False, True, False

    if args.only == "generate":
        return False, False, True

    return (
        not args.skip_collect,
        not args.skip_process,
        not args.skip_generate,
    )


def run_edition(
    reporting_date: str,
    date_reason: str,
    args: argparse.Namespace,
    edition_number: int,
) -> bool:
    """
    Run the complete pipeline for exactly one reporting edition.

    Returns True when every executed stage succeeded.
    """

    try:
        resolved_date = parse_ist_date(reporting_date)
    except (TypeError, ValueError):
        print(
            "ERROR: Reporting-date resolver returned "
            "an invalid date.",
            file=sys.stderr,
        )
        return False

    if resolved_date is None:
        print(
            "ERROR: Reporting-date resolver returned "
            "an invalid date.",
            file=sys.stderr,
        )
        return False

    window_start, window_end = (
        ist_day_window(reporting_date)
    )

    covered_day = (
        resolved_date
        - timedelta(days=1)
    ).isoformat()

    (
        run_collect,
        run_process,
        run_generate,
    ) = selected_phases(args)

    print()
    print("TechPulse — Pipeline Runner")
    print("=" * 50)

    if edition_number > 1:
        print(f"Edition #{edition_number} (catch-up)")

    print(
        f"Reporting date : {reporting_date} "
        "(edition, Asia/Kolkata)"
    )

    print(
        f"Covers IST day : {covered_day}"
    )

    print(
        f"Window (UTC)   : "
        f"{window_start.isoformat()} -> "
        f"{window_end.isoformat()}"
    )

    print(
        f"IST now        : {ist_now().isoformat()}"
    )

    print(
        f"Date resolved  : {date_reason}"
    )

    print(
        "Phases         : "
        f"{'collect ' if run_collect else ''}"
        f"{'process ' if run_process else ''}"
        f"{'generate' if run_generate else ''}"
    )

    print()

    overall_success = True

    collector_failures = 0
    collector_total = 0

    # ================================================================ #
    # Phase 1: Collect
    # ================================================================ #

    if run_collect:
        print("Phase 1: Source Collection")
        print("-" * 30)

        collector_results: list[
            tuple[str, bool]
        ] = []

        for (
            name,
            script,
            takes_date,
            timeout,
        ) in COLLECTORS:
            stage_args = (
                [
                    "--date",
                    reporting_date,
                ]
                if takes_date
                else []
            )

            start = time.time()

            success, output = run_script(
                script,
                stage_args,
                timeout,
            )

            elapsed = (
                time.time() - start
            )

            collector_total += 1

            if not success:
                collector_failures += 1

            collector_results.append(
                (
                    name,
                    success,
                )
            )

            print_stage(
                f"{name} ({elapsed:.1f}s)",
                success,
                output,
                args.verbose,
            )

        print()

        # Every collector failed. This is a fatal source outage and
        # there is no trustworthy source data from which to continue.
        if (
            collector_total > 0
            and collector_failures
            == collector_total
        ):
            print(
                "Pipeline failed: every collector failed; "
                "processing and generation were not attempted. ✗",
                file=sys.stderr,
            )
            return False

    # ================================================================ #
    # Phase 2: Process
    # ================================================================ #

    if run_process:
        print("Phase 2: Data Processing")
        print("-" * 30)

        for (
            name,
            script,
            takes_date,
            timeout,
        ) in PROCESSORS:
            stage_args = (
                [
                    "--date",
                    reporting_date,
                ]
                if takes_date
                else []
            )

            start = time.time()

            success, output = run_script(
                script,
                stage_args,
                timeout,
            )

            elapsed = (
                time.time() - start
            )

            if not success:
                overall_success = False

            print_stage(
                f"{name} ({elapsed:.1f}s)",
                success,
                output,
                args.verbose,
            )

        print()

    # ================================================================ #
    # Phase 3: Generate
    # ================================================================ #

    if run_generate:
        print("Phase 3: Data Generation")
        print("-" * 30)

        for (
            name,
            script,
            takes_date,
            timeout,
        ) in GENERATORS:
            stage_args = (
                [
                    "--date",
                    reporting_date,
                ]
                if takes_date
                else []
            )

            start = time.time()

            success, output = run_script(
                script,
                stage_args,
                timeout,
            )

            elapsed = (
                time.time() - start
            )

            if not success:
                overall_success = False

            print_stage(
                f"{name} ({elapsed:.1f}s)",
                success,
                output,
                args.verbose,
            )

        print()

    # ================================================================ #
    # Edition summary
    # ================================================================ #

    print("=" * 50)

    if run_collect and collector_failures:
        successful_collectors = (
            collector_total
            - collector_failures
        )

        print(
            f"Source health: "
            f"{successful_collectors}/"
            f"{collector_total} "
            "collectors succeeded. "
            "Failed collectors are recorded in "
            "source-health data."
        )

    if overall_success:
        print(
            "Pipeline completed successfully ✓  "
            f"(edition {reporting_date})"
        )
        return True

    print(
        "Pipeline completed with failures ✗",
        file=sys.stderr,
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the TechPulse data pipeline."
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Reporting date (YYYY-MM-DD, IST edition). "
            "Default: next pending edition."
        ),
    )

    parser.add_argument(
        "--catch-up",
        action="store_true",
        help=(
            "After the first edition, keep processing further "
            "pending editions (bounded by MAX_EDITIONS_PER_RUN) "
            "until the archive catches up with the current IST "
            "date. Requires the full pipeline."
        ),
    )

    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="Skip source collection.",
    )

    parser.add_argument(
        "--skip-process",
        action="store_true",
        help="Skip data processing.",
    )

    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Skip data generation.",
    )

    parser.add_argument(
        "--only",
        choices=[
            "collect",
            "process",
            "generate",
        ],
        help="Run only one pipeline phase.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print all stage output.",
    )

    args = parser.parse_args()

    argument_error = validate_arguments(
        args
    )

    if argument_error:
        print(
            f"ERROR: {argument_error}",
            file=sys.stderr,
        )
        return 1

    processed: list[str] = []
    failed: list[str] = []

    # Explicit --date without --catch-up processes exactly one
    # edition, matching historical behavior.
    max_editions = (
        MAX_EDITIONS_PER_RUN
        if args.catch_up
        else 1
    )

    pending_start_date = args.date

    while (
        len(processed) + len(failed)
        < max_editions
    ):
        if pending_start_date is not None:
            reporting_date = pending_start_date
            date_reason = (
                f"explicit input date {pending_start_date}"
            )
            pending_start_date = None
        else:
            try:
                (
                    reporting_date,
                    date_reason,
                ) = resolve_reporting_date(
                    "manual",
                    None,
                )
            except ValueError as exc:
                print(
                    f"ERROR: {exc}",
                    file=sys.stderr,
                )
                if processed:
                    break

                return 1

        # The resolver can legitimately return an edition that was
        # already processed in this run (for example after catching
        # up to the current IST date). That is the steady state and
        # means catch-up is complete.
        if reporting_date in processed:
            break

        edition_number = len(processed) + len(failed) + 1

        edition_success = run_edition(
            reporting_date,
            date_reason,
            args,
            edition_number,
        )

        if edition_success:
            processed.append(reporting_date)
        else:
            failed.append(reporting_date)

            # A failed edition blocks resolution of later pending
            # editions (the resolver always picks the oldest
            # pending date), so stop this run. Editions that already
            # completed remain valid and will be committed.
            break

    print()
    print("=" * 50)
    print(
        "Editions processed this run: "
        f"{len(processed)}"
    )

    for date in processed:
        print(f"  ✓ {date}")

    if failed:
        print(
            "Editions failed this run: "
            f"{len(failed)}"
        )

        for date in failed:
            print(f"  ✗ {date}")

        if processed:
            print(
                "Completed editions are valid and will be "
                "published; failed editions are retried on the "
                "next run.",
                file=sys.stderr,
            )

    if failed and not processed:
        print(
            "Pipeline completed with failures ✗",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())