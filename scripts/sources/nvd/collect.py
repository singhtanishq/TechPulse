#!/usr/bin/env python3

"""
TechPulse — NVD Collector

Collects recently published/modified CVE records from the
National Vulnerability Database (NVD) 2.0 API and stores
normalized JSON data for downstream processing.

This collector is intentionally independent from the frontend.
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

# NVD recommends respecting its API rate limits.
# Keep requests conservative for the free/no-key workflow.
REQUEST_DELAY_SECONDS = 6
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def format_nvd_datetime(value: datetime) -> str:
    """
    Format datetime for NVD API query parameters.

    NVD expects ISO-8601 timestamps.
    """
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime string."""
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


def normalize_cve(vulnerability: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw NVD vulnerability object into TechPulse format."""

    cve = vulnerability.get("cve", {})

    cvss = extract_cvss(cve)

    return {
        "id": cve.get("id"),
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


def fetch_page_with_retry(
    start_index: int,
    results_per_page: int,
    start_date: datetime,
    end_date: datetime,
) -> dict[str, Any]:
    """
    Fetch a single page from NVD API with retry logic for transient failures.
    """

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
            "User-Agent": "TechPulse/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT,
            ) as response:

                status = response.status

                if status == 429:
                    # Rate limited - wait longer and retry
                    wait_time = REQUEST_DELAY_SECONDS * (attempt + 1) * 2
                    print(
                        f"Rate limited (429). Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue

                if status != 200:
                    raise RuntimeError(
                        f"NVD API returned unexpected HTTP status {status}"
                    )

                raw = response.read()

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait_time = REQUEST_DELAY_SECONDS * (attempt + 1) * 2
                print(
                    f"Rate limited (429). Waiting {wait_time}s before retry..."
                )
                time.sleep(wait_time)
                last_exception = exc
                continue
            if 500 <= exc.code < 600:
                # Server error - retry
                wait_time = RETRY_BACKOFF_BASE ** attempt
                print(
                    f"Server error ({exc.code}). Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                last_exception = exc
                continue
            raise RuntimeError(
                f"NVD API returned HTTP {exc.code}: {exc.reason}"
            ) from exc

        except urllib.error.URLError as exc:
            # Network error - retry
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(
                f"Network error: {exc.reason}. Retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
            last_exception = exc
            continue

        except Exception as exc:
            last_exception = exc
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(
                f"Unexpected error: {exc}. Retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
            continue

        try:
            return json.loads(raw.decode("utf-8"))

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "NVD API returned invalid JSON."
            ) from exc

    # All retries exhausted
    if last_exception:
        raise RuntimeError(
            f"Failed after {MAX_RETRIES} attempts: {last_exception}"
        ) from last_exception

    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")


def collect(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """
    Collect vulnerabilities from NVD within the given date window.

    Returns deduplicated, deterministically sorted list of normalized CVEs.
    """

    vulnerabilities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    start_index = 0
    total_results: int | None = None

    while True:

        print(
            f"Fetching NVD records "
            f"starting at index {start_index}..."
        )

        data = fetch_page_with_retry(
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
            cve_id = normalized.get("id")
            if cve_id and cve_id not in seen_ids:
                seen_ids.add(cve_id)
                vulnerabilities.append(normalized)

        start_index += len(page_results)

        if start_index >= total_results:
            break

        if not page_results:
            break

        print(
            f"Waiting {REQUEST_DELAY_SECONDS}s before "
            "the next NVD request..."
        )

        time.sleep(REQUEST_DELAY_SECONDS)

    # Deterministic sort: by CVE ID ascending
    vulnerabilities.sort(key=lambda v: v.get("id", ""))

    return vulnerabilities


def save_output(
    vulnerabilities: list[dict[str, Any]],
    start_date: datetime,
    end_date: datetime,
) -> Path:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    collection_date = utc_now().date().isoformat()

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

    output_path = OUTPUT_DIR / f"{collection_date}.json"

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )

        file.write("\n")

    return output_path


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Collect recent CVEs from the NVD API."
    )

    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hours to look back. Default: 24.",
    )

    parser.add_argument(
        "--start",
        type=str,
        help="Explicit UTC ISO-8601 start datetime.",
    )

    parser.add_argument(
        "--end",
        type=str,
        help="Explicit UTC ISO-8601 end datetime.",
    )

    args = parser.parse_args()

    if args.hours <= 0:
        parser.error("--hours must be greater than zero.")

    if args.start and args.end:

        start_date = parse_datetime(args.start)
        end_date = parse_datetime(args.end)

    elif args.start or args.end:

        parser.error(
            "--start and --end must be supplied together."
        )

    else:

        end_date = utc_now()

        start_date = end_date - timedelta(
            hours=args.hours
        )

    if start_date >= end_date:
        parser.error(
            "Start datetime must be earlier than end datetime."
        )

    print()
    print("TechPulse — NVD Collector")
    print("=" * 32)
    print(f"Start : {format_nvd_datetime(start_date)}")
    print(f"End   : {format_nvd_datetime(end_date)}")
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

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    print()
    print("Collection completed successfully.")
    print(f"Records : {len(vulnerabilities)}")
    print(f"Output  : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())