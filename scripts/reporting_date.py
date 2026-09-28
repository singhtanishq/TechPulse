#!/usr/bin/env python3

"""
TechPulse — Reporting Date Resolver (CLI)

Resolves the TechPulse reporting date for a pipeline run and prints it
in a machine-readable form for GitHub Actions:

    REPORTING_DATE=YYYY-MM-DD

Human-readable context is printed to stderr so workflow logs explain
exactly which India date is being processed and why.

The TechPulse reporting model (see scripts/config/snapshot.json):
    - Reporting dates are India calendar days (Asia/Kolkata, UTC+05:30).
    - The edition for date X covers the previous IST day (X-1) and is
      published at the start of day X (workflow fires 18:30 UTC).
    - Resolution for scheduled runs ignores the runner's execution
      instant as an anchor: explicit input > next pending edition
      (newest snapshot + 1) > current IST date with a 90-minute
      forward jitter buffer. min() of the candidates keeps the run
      self-healing (backfills missed days) without ever skipping ahead.

Usage:
    python3 scripts/reporting_date.py [--event schedule|push|workflow_dispatch|manual]
                                      [--input-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    ist_day_window,
    ist_now,
    ist_today,
    newest_snapshot_date,
    resolve_reporting_date,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the TechPulse reporting date.")
    parser.add_argument(
        "--event",
        choices=["schedule", "push", "workflow_dispatch", "manual"],
        default="manual",
        help="Triggering event (schedule runs get the midnight-jitter buffer).",
    )
    parser.add_argument(
        "--input-date",
        default=None,
        help="Explicit reporting date override (YYYY-MM-DD, IST).",
    )
    args = parser.parse_args()

    try:
        reporting_date, reason = resolve_reporting_date(args.event, args.input_date)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    window_start, window_end = ist_day_window(reporting_date)
    covered_day = (
        window_start.astimezone(__import__("datetime").timezone(
            __import__("datetime").timedelta(hours=5, minutes=30)
        )).date().isoformat()
    )

    print(f"REPORTING_DATE={reporting_date}")
    print(f"Resolved via : {reason}", file=sys.stderr)
    print(f"Reporting date (edition, IST): {reporting_date}", file=sys.stderr)
    print(f"Covers IST day               : {covered_day}", file=sys.stderr)
    print(f"Window (UTC)                 : {window_start.isoformat()} -> {window_end.isoformat()}", file=sys.stderr)
    print(f"IST now                      : {ist_now().isoformat()}", file=sys.stderr)
    print(f"IST today (no buffer)        : {ist_today()}", file=sys.stderr)
    print(f"Newest existing snapshot     : {newest_snapshot_date() or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
