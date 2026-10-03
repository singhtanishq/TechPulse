#!/usr/bin/env python3

"""
TechPulse — Reporting Date Resolver (CLI)

Resolves the TechPulse reporting date for a pipeline run and prints it
in a machine-readable form for GitHub Actions:

    REPORTING_DATE=YYYY-MM-DD

Human-readable context is printed to stderr so workflow logs explain
exactly which India date is being processed and why.

The TechPulse reporting model:
    - Reporting dates are India calendar days (Asia/Kolkata, UTC+05:30).
    - The edition for date X covers the previous IST day (X-1).
    - Scheduled runs use the shared resolver in processors.utils so
      backfills and missed editions are handled consistently.
    - Explicit input always takes precedence over automatic resolution.

Usage:
    python3 scripts/reporting_date.py
    python3 scripts/reporting_date.py --event schedule
    python3 scripts/reporting_date.py --input-date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    ist_day_window,
    ist_now,
    ist_today,
    newest_snapshot_date,
    parse_ist_date,
    resolve_reporting_date,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the TechPulse reporting date "
            "for a pipeline run."
        )
    )

    parser.add_argument(
        "--event",
        choices=[
            "schedule",
            "push",
            "workflow_dispatch",
            "manual",
        ],
        default="manual",
        help=(
            "Triggering event. Resolution behavior is "
            "handled centrally by processors.utils."
        ),
    )

    parser.add_argument(
        "--input-date",
        default=None,
        help=(
            "Explicit reporting date override "
            "(YYYY-MM-DD, IST)."
        ),
    )

    args = parser.parse_args()

    try:
        reporting_date, reason = resolve_reporting_date(
            args.event,
            args.input_date,
        )
    except ValueError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    # Never allow an invalid value returned by the shared resolver
    # to reach GitHub Actions as REPORTING_DATE.
    parsed_reporting_date = parse_ist_date(
        reporting_date
    )

    if parsed_reporting_date is None:
        print(
            "ERROR: Resolver returned an invalid "
            "reporting date.",
            file=sys.stderr,
        )
        return 1

    window_start, window_end = ist_day_window(
        reporting_date
    )

    covered_day = (
        parsed_reporting_date
        - timedelta(days=1)
    ).isoformat()

    # Machine-readable output must remain on stdout.
    # All diagnostics belong on stderr.
    print(
        f"REPORTING_DATE={reporting_date}"
    )

    print(
        f"Resolved via : {reason}",
        file=sys.stderr,
    )

    print(
        f"Reporting date (edition, IST): "
        f"{reporting_date}",
        file=sys.stderr,
    )

    print(
        f"Covers IST day               : "
        f"{covered_day}",
        file=sys.stderr,
    )

    print(
        f"Window (UTC)                 : "
        f"{window_start.isoformat()} -> "
        f"{window_end.isoformat()}",
        file=sys.stderr,
    )

    print(
        f"IST now                      : "
        f"{ist_now().isoformat()}",
        file=sys.stderr,
    )

    print(
        f"IST today                    : "
        f"{ist_today()}",
        file=sys.stderr,
    )

    print(
        f"Newest existing snapshot     : "
        f"{newest_snapshot_date() or 'none'}",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
