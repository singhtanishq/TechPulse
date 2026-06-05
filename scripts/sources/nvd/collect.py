#!/usr/bin/env python3

"""
TechPulse — NVD Collector

Collects CVE records for a target UTC calendar day from the
National Vulnerability Database (NVD) 2.0 API and stores
normalized JSON data for downstream processing.

Snapshot semantics:
    A snapshot covers one UTC calendar day (00:00:00Z - 23:59:59.999Z).
    The default target date is the previous completed UTC day.

Output:
    data/security/nvd/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with identical records does not
    rewrite the output file (preserves the original collectedAt).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

PROJECT_ROOT = Path(__file__).resolve().parents[3]

OUTPUT_DIR = PROJECT_ROOT / "data" / "security" / "nvd"

DEFAULT_RESULTS_PER_PAGE = 2000
REQUEST_TIMEOUT = 30
PAGE_TIMEOUT_SECONDS = 120

# NVD rate limits unauthenticated clients aggressively.
# Keep requests conservative for the free/no-key workflow.
REQUEST_DELAY_SECONDS = 6
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def default_snapshot_date() -> datetime:
    """Return the previous completed UTC day at midnight."""
    yesterday = (utc_now() - timedelta(days=1)).date()
    return datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)


def format_nvd_datetime(value: datetime) -> str:
    """Format datetime for NVD API query parameters (ISO-8601, milliseconds, Z)."""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def get_description(cve: dict[str, Any]) -> str:
    """Extract the English CVE description when available."""

    descriptions = cve.get("descriptions", [])

    for item in descriptions:
        if item.get("lang") == "en":
            return item.get("value", "").strip()

    if descriptions:
        return descriptions[0].get("value", "").strip()

    return ""


def extract_cvss(cve: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract the highest-priority CVSS metric available from the
    NVD response.

    Preference:
        CVSS v4.0
        CVSS v3.1
        CVSS v3.0
        CVSS v2.0

    Records without any CVSS metric are valid NVD records; the
    caller must represent the missing score explicitly as null.
    """

    metrics = cve.get("metrics", {})

    metric_preferences = [
        ("cvssMetricV40", "4.0"),
        ("cvssMetricV31", "3.1"),
        ("cvssMetricV30", "3.0"),
        ("cvssMetricV2", "2.0"),
    ]

    for key, version in metric_preferences:
        entries = metrics.get(key)

        if not entries:
            continue

        # Prefer the NVD-assigned metric where present.
        preferred = next(
            (
                entry
                for entry in entries
                if entry.get("type") == "Primary"
            ),
            entries[0],
        )

        cvss_data = preferred.get("cvssData", {})

        score = cvss_data.get("baseScore")

        if score is None:
            continue

        return {
            "version": version,
            "score": score,
            "severity": cvss_data.get("baseSeverity"),
            "vector": cvss_data.get("vectorString"),
        }

    return None


def normalize_cve(vulnerability: dict[str, Any]) -> dict[str, Any] | None:
    """
    Convert a raw NVD vulnerability object into TechPulse format.

    Returns None for records without a CVE ID (structurally invalid).
    """

    cve = vulnerability.get("cve", {})

    cve_id = cve.get("id")

    if not cve_id:
        return None

    cvss = extract_cvss(cve)

    return {
        "id": cve_id,
        "source": "NVD",
        "published": cve.get("published"),
        "lastModified": cve.get("lastModified"),
        "description": get_description(cve),
        "severity": cvss.get("severity") if cvss else None,
        "cvss": cvss,
        "references": [
            ref.get("url")
            for ref in cve.get("references", [])
            if ref.get("url")
        ],
    }


def fetch_page(
    start_index: int,
    results_per_page: int,
    start_date: datetime,
    end_date: datetime,
) -> dict[str, Any]:
    """Fetch a single page from the NVD API with conservative retries."""

    params = {
        "startIndex": start_index,
        "resultsPerPage": results_per_page,
        "lastModStartDate": format_nvd_datetime(start_date),
        "lastModEndDate": format_nvd_datetime(end_date),
    }

    url = f"{API_URL}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TechPulse/1.0 (+https://github.com/singhtanishq/TechPulse)",
            "Accept": "application/json",
        },
        method="GET",
    )

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):

        if attempt > 0:
            wait = RETRY_BACKOFF_BASE ** attempt * REQUEST_DELAY_SECONDS
            print(f"  Retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)

        try:
            with urllib.request.urlopen(
                request,
                timeout=PAGE_TIMEOUT_SECONDS,
            ) as response:
                status = response.status
                raw = response.read()

            if status == 429:
                print("  NVD rate limit hit (429).")
                last_error = RuntimeError("NVD API returned HTTP 429 (rate limited)")
                continue

            if status != 200:
                last_error = RuntimeError(f"NVD API returned HTTP {status}")
                continue

            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("NVD API returned invalid JSON.") from exc

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                print("  NVD rate limit hit (429).")
                last_error = RuntimeError("NVD API returned HTTP 429 (rate limited)")
                continue
            if 500 <= exc.code < 600:
                print(f"  NVD server error ({exc.code}).")
                last_error = RuntimeError(f"NVD API returned HTTP {exc.code}: {exc.reason}")
                continue
            raise RuntimeError(f"NVD API returned HTTP {exc.code}: {exc.reason}") from exc

        except urllib.error.URLError as exc:
            print(f"  Network error reaching NVD: {exc.reason}")
            last_error = RuntimeError(f"Unable to reach NVD API: {exc.reason}")
            continue

        except RuntimeError:
            raise

        except Exception as exc:
            print(f"  Unexpected error fetching NVD page: {exc}")
            last_error = RuntimeError(f"Unexpected NVD error: {exc}")
            continue

    raise RuntimeError(
        f"NVD request failed after {MAX_RETRIES} attempts: {last_error}"
    ) from last_error


def collect(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """
    Collect CVEs modified within [start_date, end_date] from NVD.

    Returns a deduplicated list sorted deterministically by CVE ID.
    """

    vulnerabilities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    start_index = 0
    total_results: int | None = None

    while True:

        print(f"Fetching NVD records starting at index {start_index}...")

        data = fetch_page(
            start_index=start_index,
            results_per_page=DEFAULT_RESULTS_PER_PAGE,
            start_date=start_date,
            end_date=end_date,
        )

        total_results = data.get("totalResults", 0)
        page_results = data.get("vulnerabilities", [])

        print(
            f"Received {len(page_results)} records "
            f"(total matching: {total_results})"
        )

        for item in page_results:
            normalized = normalize_cve(item)
            if normalized is None:
                continue
            if normalized["id"] not in seen_ids:
                seen_ids.add(normalized["id"])
                vulnerabilities.append(normalized)

        start_index += len(page_results)

        if total_results == 0 or not page_results:
            break

        if start_index >= total_results:
            break

        print(f"Waiting {REQUEST_DELAY_SECONDS}s before the next NVD request...")
        time.sleep(REQUEST_DELAY_SECONDS)

    # Deterministic ordering: CVE ID ascending.
    vulnerabilities.sort(key=lambda v: v["id"])

    return vulnerabilities


def records_fingerprint(vulnerabilities: list[dict[str, Any]]) -> str:
    """Return a stable fingerprint of the record set (ignores meta)."""
    return json.dumps(vulnerabilities, sort_keys=True, ensure_ascii=False)


def save_output(
    vulnerabilities: list[dict[str, Any]],
    start_date: datetime,
    end_date: datetime,
) -> Path:
    """
    Save output for the snapshot date, idempotently.

    If the file for this date already exists with identical records,
    it is left untouched (preserving the original collectedAt).
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    snapshot_date = end_date.date().isoformat()

    output_path = OUTPUT_DIR / f"{snapshot_date}.json"

    new_records = records_fingerprint(vulnerabilities)

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            existing_records = records_fingerprint(existing.get("vulnerabilities", []))
            if existing_records == new_records:
                print(
                    f"Records unchanged for {snapshot_date}; "
                    f"keeping existing file (idempotent skip)."
                )
                return output_path
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt existing file: overwrite with fresh data.

    output = {
        "meta": {
            "source": "NVD",
            "collectedAt": utc_now().isoformat(),
            "window": {
                "start": format_nvd_datetime(start_date),
                "end": format_nvd_datetime(end_date),
            },
            "count": len(vulnerabilities),
        },
        "vulnerabilities": vulnerabilities,
    }

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False, sort_keys=True)
        file.write("\n")

    return output_path


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Collect CVEs modified on a target UTC calendar day from the NVD API."
    )

    parser.add_argument(
        "--date",
        type=str,
        help="Snapshot date (YYYY-MM-DD, UTC). Default: previous completed UTC day.",
    )

    parser.add_argument(
        "--start",
        type=str,
        help="Explicit UTC ISO-8601 window start (overrides --date).",
    )

    parser.add_argument(
        "--end",
        type=str,
        help="Explicit UTC ISO-8601 window end (overrides --date).",
    )

    args = parser.parse_args()

    if args.start and args.end:
        start_date = parse_datetime(args.start)
        end_date = parse_datetime(args.end)
    elif args.start or args.end:
        parser.error("--start and --end must be supplied together.")
    elif args.date:
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            parser.error("--date must be in YYYY-MM-DD format.")
        start_date = day
        end_date = day + timedelta(days=1) - timedelta(milliseconds=1)
    else:
        start_date = default_snapshot_date()
        end_date = start_date + timedelta(days=1) - timedelta(milliseconds=1)

    if start_date >= end_date:
        parser.error("Start datetime must be earlier than end datetime.")

    print()
    print("TechPulse — NVD Collector")
    print("=" * 32)
    print(f"Snapshot date : {end_date.date().isoformat()}")
    print(f"Window start  : {format_nvd_datetime(start_date)}")
    print(f"Window end    : {format_nvd_datetime(end_date)}")
    print()

    try:
        vulnerabilities = collect(
            start_date=start_date,
            end_date=end_date,
        )
        output_path = save_output(
            vulnerabilities=vulnerabilities,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Collection completed successfully.")
    print(f"Records : {len(vulnerabilities)}")
    print(f"Output  : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
