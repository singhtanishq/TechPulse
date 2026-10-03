#!/usr/bin/env python3

"""
TechPulse — NVD Collector

Collects CVE records for a target reporting day from the National
Vulnerability Database (NVD) 2.0 API and stores normalized JSON data
for downstream processing.

Snapshot semantics:
    The reporting date is an India calendar day (Asia/Kolkata). The
    edition for date X covers the previous completed IST day:
    [X-1 00:00 IST, X 00:00 IST), passed to NVD as UTC instants.
    The default target is the current reporting date.

    When an explicit --start/--end window is supplied without --date,
    the reporting date is derived from the instant immediately after
    the inclusive end of that window.

Output:
    data/security/nvd/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with identical records and matching
    reporting metadata does not rewrite the output file.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.parse
import urllib.request

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import (  # noqa: E402
    ist_date_of,
    ist_day_window,
    ist_today,
    parse_iso_datetime,
    parse_ist_date,
)


API_URL = (
    "https://services.nvd.nist.gov/rest/json/cves/2.0"
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

OUTPUT_DIR = PROJECT_ROOT / "data" / "security" / "nvd"

DEFAULT_RESULTS_PER_PAGE = 2000
PAGE_TIMEOUT_SECONDS = 120

# NVD rate limits unauthenticated clients aggressively.
# Keep requests conservative for the free/no-key workflow.
REQUEST_DELAY_SECONDS = 6
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2

MAX_RESPONSE_BYTES = 50 * 1024 * 1024

CVE_ID_PATTERN = re.compile(
    r"^CVE-\d{4}-\d{4,}$",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def resolve_window(
    date_arg: str | None,
    start_arg: str | None,
    end_arg: str | None,
) -> tuple[datetime, datetime]:
    """
    Resolve the NVD collection window.

    --date is the TechPulse reporting date (IST edition); its window is
    the previous completed IST calendar day.

    Explicit --start/--end (ISO-8601, any offset) override --date and
    are used exactly as supplied.
    """
    if start_arg and end_arg:
        start = parse_iso_datetime(start_arg)
        end = parse_iso_datetime(end_arg)

        if start is None or end is None:
            raise ValueError(
                "--start/--end must be valid ISO-8601 datetimes."
            )

        if start >= end:
            raise ValueError(
                "--start datetime must be earlier than --end datetime."
            )

        return start, end

    if start_arg or end_arg:
        raise ValueError(
            "--start and --end must be supplied together."
        )

    reporting_date = date_arg or ist_today()

    if parse_ist_date(reporting_date) is None:
        raise ValueError(
            "--date must be in YYYY-MM-DD format."
        )

    start, end = ist_day_window(reporting_date)

    # The NVD range is inclusive. Stop at the last millisecond before
    # the next IST reporting boundary so adjacent editions cannot
    # overlap.
    return start, end - timedelta(milliseconds=1)


def resolve_reporting_date(
    date_arg: str | None,
    start_arg: str | None,
    end_arg: str | None,
    end_date: datetime,
) -> str:
    """
    Resolve the filename/reporting-date label for the collection.

    Explicit --date always wins.

    For an explicit --start/--end window without --date, the reporting
    date is the IST calendar date immediately after the inclusive end
    instant. This keeps the output filename tied to the supplied window
    instead of silently using today's date.
    """
    if date_arg:
        if parse_ist_date(date_arg) is None:
            raise ValueError(
                "--date must be in YYYY-MM-DD format."
            )
        return date_arg

    if start_arg and end_arg:
        reporting_instant = end_date + timedelta(milliseconds=1)
        return ist_date_of(reporting_instant)

    return ist_today()


def format_nvd_datetime(value: datetime) -> str:
    """Format datetime for NVD API query parameters."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def get_description(cve: dict[str, Any]) -> str:
    """Extract the English CVE description when available."""

    descriptions = cve.get("descriptions", [])

    if not isinstance(descriptions, list):
        return ""

    fallback = ""

    for item in descriptions:
        if not isinstance(item, dict):
            continue

        value = item.get("value")
        if not isinstance(value, str):
            continue

        value = value.strip()

        if not value:
            continue

        if not fallback:
            fallback = value

        if item.get("lang") == "en":
            return value

    return fallback


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
    caller represents the missing score explicitly as null.
    """

    metrics = cve.get("metrics", {})

    if not isinstance(metrics, dict):
        return None

    metric_preferences = [
        ("cvssMetricV40", "4.0"),
        ("cvssMetricV31", "3.1"),
        ("cvssMetricV30", "3.0"),
        ("cvssMetricV2", "2.0"),
    ]

    for key, version in metric_preferences:
        entries = metrics.get(key)

        if not isinstance(entries, list) or not entries:
            continue

        valid_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict)
        ]

        if not valid_entries:
            continue

        # Prefer the NVD-assigned metric where present.
        preferred = next(
            (
                entry
                for entry in valid_entries
                if entry.get("type") == "Primary"
            ),
            valid_entries[0],
        )

        cvss_data = preferred.get("cvssData")

        if not isinstance(cvss_data, dict):
            continue

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


def normalize_cve(
    vulnerability: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Convert a raw NVD vulnerability object into TechPulse format.

    Returns None for structurally invalid records without a valid
    CVE identifier.
    """

    if not isinstance(vulnerability, dict):
        return None

    cve = vulnerability.get("cve", {})

    if not isinstance(cve, dict):
        return None

    raw_cve_id = cve.get("id")

    if not isinstance(raw_cve_id, str):
        return None

    cve_id = raw_cve_id.strip().upper()

    if not CVE_ID_PATTERN.fullmatch(cve_id):
        return None

    cvss = extract_cvss(cve)

    # NVD responses can contain the same reference URL multiple times.
    # Deduplicate while preserving first-seen order.
    references: list[str] = []
    seen_refs: set[str] = set()

    raw_references = cve.get("references", [])

    if isinstance(raw_references, list):
        for ref in raw_references:
            if not isinstance(ref, dict):
                continue

            url = ref.get("url")

            if not isinstance(url, str):
                continue

            url = url.strip()

            if not url or url in seen_refs:
                continue

            seen_refs.add(url)
            references.append(url)

    published = cve.get("published")
    last_modified = cve.get("lastModified")

    if not isinstance(published, str):
        published = None

    if not isinstance(last_modified, str):
        last_modified = None

    return {
        "id": cve_id,
        "source": "NVD",
        "published": published,
        "lastModified": last_modified,
        "description": get_description(cve),
        "severity": cvss.get("severity") if cvss else None,
        "cvss": cvss,
        "references": references,
    }


def _read_response_body(response: Any) -> bytes:
    """Read an NVD response while enforcing a maximum response size."""

    content_length = response.headers.get("Content-Length")

    if content_length:
        try:
            declared_size = int(content_length)

            if declared_size > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    "NVD API response is too large."
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = response.read(64 * 1024)

        if not chunk:
            break

        total_size += len(chunk)

        if total_size > MAX_RESPONSE_BYTES:
            raise RuntimeError(
                "NVD API response exceeded the maximum allowed size."
            )

        chunks.append(chunk)

    return b"".join(chunks)


def _retry_after_seconds(value: str | None) -> int | None:
    """Parse Retry-After as either seconds or an HTTP date."""

    if not value:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        seconds = int(value)
        return max(0, min(seconds, 120))
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(value)

        if retry_at is None:
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        seconds = int(
            (
                retry_at.astimezone(timezone.utc)
                - utc_now()
            ).total_seconds()
        )

        return max(0, min(seconds, 120))

    except (TypeError, ValueError, OverflowError):
        return None


def _retry_delay_seconds(
    attempt: int,
    retry_after: str | None = None,
) -> int:
    """Calculate a bounded retry delay."""

    retry_after_seconds = _retry_after_seconds(retry_after)

    if retry_after_seconds is not None:
        return retry_after_seconds

    return (
        RETRY_BACKOFF_BASE ** attempt
        * REQUEST_DELAY_SECONDS
    )


def _validate_page_payload(payload: Any) -> tuple[int, list[Any]]:
    """
    Validate the minimum NVD API response structure required by the
    collector.
    """

    if not isinstance(payload, dict):
        raise RuntimeError(
            "NVD API returned a response that is not a JSON object."
        )

    total_results = payload.get("totalResults")
    vulnerabilities = payload.get("vulnerabilities")

    if (
        isinstance(total_results, bool)
        or not isinstance(total_results, int)
        or total_results < 0
    ):
        raise RuntimeError(
            "NVD API returned an invalid totalResults value."
        )

    if not isinstance(vulnerabilities, list):
        raise RuntimeError(
            "NVD API returned an invalid vulnerabilities collection."
        )

    return total_results, vulnerabilities


def fetch_page(
    start_index: int,
    results_per_page: int,
    start_date: datetime,
    end_date: datetime,
) -> dict[str, Any]:
    """Fetch a single page from the NVD API with conservative retries."""

    if start_index < 0:
        raise ValueError("start_index cannot be negative.")

    if results_per_page <= 0:
        raise ValueError(
            "results_per_page must be greater than zero."
        )

    if start_date.tzinfo is None:
        start_date = start_date.replace(
            tzinfo=timezone.utc
        )

    if end_date.tzinfo is None:
        end_date = end_date.replace(
            tzinfo=timezone.utc
        )

    if start_date >= end_date:
        raise ValueError(
            "start_date must be earlier than end_date."
        )

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
            "User-Agent": (
                "TechPulse/1.0 "
                "(+https://github.com/singhtanishq/TechPulse)"
            ),
            "Accept": "application/json",
        },
        method="GET",
    )

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait = _retry_delay_seconds(
                attempt,
                getattr(fetch_page, "_retry_after", None),
            )

            print(
                f"  Retrying in {wait}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})..."
            )

            if wait > 0:
                time.sleep(wait)

            fetch_page._retry_after = None

        try:
            with urllib.request.urlopen(
                request,
                timeout=PAGE_TIMEOUT_SECONDS,
            ) as response:
                status = getattr(response, "status", 200)
                raw = _read_response_body(response)

            if status == 429:
                print("  NVD rate limit hit (429).")

                last_error = RuntimeError(
                    "NVD API returned HTTP 429 (rate limited)"
                )

                fetch_page._retry_after = None
                continue

            if status != 200:
                last_error = RuntimeError(
                    f"NVD API returned HTTP {status}"
                )
                continue

            try:
                payload = json.loads(
                    raw.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise RuntimeError(
                    "NVD API returned invalid JSON."
                ) from exc

            _validate_page_payload(payload)

            return payload

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                print("  NVD rate limit hit (429).")

                last_error = RuntimeError(
                    "NVD API returned HTTP 429 (rate limited)"
                )

                fetch_page._retry_after = (
                    exc.headers.get("Retry-After")
                    if exc.headers
                    else None
                )

                continue

            if 500 <= exc.code < 600:
                print(
                    f"  NVD server error ({exc.code})."
                )

                last_error = RuntimeError(
                    f"NVD API returned HTTP {exc.code}: "
                    f"{exc.reason}"
                )

                continue

            raise RuntimeError(
                f"NVD API returned HTTP {exc.code}: "
                f"{exc.reason}"
            ) from exc

        except urllib.error.URLError as exc:
            print(
                f"  Network error reaching NVD: "
                f"{exc.reason}"
            )

            last_error = RuntimeError(
                f"Unable to reach NVD API: {exc.reason}"
            )

            continue

        except TimeoutError:
            print("  NVD request timed out.")

            last_error = RuntimeError(
                "NVD API request timed out."
            )

            continue

        except RuntimeError:
            raise

        except Exception as exc:
            print(
                f"  Unexpected error fetching NVD page: "
                f"{exc}"
            )

            last_error = RuntimeError(
                f"Unexpected NVD error: {exc}"
            )

            continue

    raise RuntimeError(
        f"NVD request failed after {MAX_RETRIES} attempts: "
        f"{last_error}"
    ) from last_error


# Attribute used only to carry Retry-After information between retry
# iterations inside fetch_page. It is initialized explicitly here so
# tests and repeated calls always start cleanly.
fetch_page._retry_after = None


def collect(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """
    Collect CVEs modified within [start_date, end_date] from NVD.

    Returns a deduplicated list sorted deterministically by CVE ID.
    """

    if start_date.tzinfo is None:
        start_date = start_date.replace(
            tzinfo=timezone.utc
        )

    if end_date.tzinfo is None:
        end_date = end_date.replace(
            tzinfo=timezone.utc
        )

    if start_date >= end_date:
        raise ValueError(
            "Collection start datetime must be earlier "
            "than the end datetime."
        )

    vulnerabilities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    start_index = 0
    total_results: int | None = None

    while True:
        print(
            "Fetching NVD records starting at "
            f"index {start_index}..."
        )

        data = fetch_page(
            start_index=start_index,
            results_per_page=DEFAULT_RESULTS_PER_PAGE,
            start_date=start_date,
            end_date=end_date,
        )

        total_results, page_results = (
            _validate_page_payload(data)
        )

        if (
            start_index + len(page_results)
            > total_results
        ):
            raise RuntimeError(
                "NVD API returned more page records than "
                "reported by totalResults."
            )

        print(
            f"Received {len(page_results)} records "
            f"(total matching: {total_results})"
        )

        for item in page_results:
            normalized = normalize_cve(item)

            if normalized is None:
                continue

            cve_id = normalized["id"]

            if cve_id not in seen_ids:
                seen_ids.add(cve_id)
                vulnerabilities.append(normalized)

        previous_index = start_index
        start_index += len(page_results)

        if total_results == 0:
            break

        if not page_results:
            break

        if start_index >= total_results:
            break

        if start_index <= previous_index:
            raise RuntimeError(
                "NVD pagination made no forward progress."
            )

        print(
            f"Waiting {REQUEST_DELAY_SECONDS}s "
            "before the next NVD request..."
        )

        if REQUEST_DELAY_SECONDS > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

    # Deterministic ordering: CVE ID ascending.
    vulnerabilities.sort(
        key=lambda v: v["id"]
    )

    return vulnerabilities


def records_fingerprint(
    vulnerabilities: list[dict[str, Any]],
) -> str:
    """Return a stable fingerprint of the record set."""
    return json.dumps(
        vulnerabilities,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def save_output(
    vulnerabilities: list[dict[str, Any]],
    start_date: datetime,
    end_date: datetime,
    reporting_date: str,
) -> Path:
    """
    Save output for the reporting date, idempotently.

    The filename carries the TechPulse reporting date (edition), never
    a date derived from the filename or filesystem state.
    """

    if parse_ist_date(reporting_date) is None:
        raise ValueError(
            "reporting_date must be in YYYY-MM-DD format."
        )

    if start_date.tzinfo is None:
        start_date = start_date.replace(
            tzinfo=timezone.utc
        )

    if end_date.tzinfo is None:
        end_date = end_date.replace(
            tzinfo=timezone.utc
        )

    if start_date >= end_date:
        raise ValueError(
            "start_date must be earlier than end_date."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / f"{reporting_date}.json"
    )

    new_records = records_fingerprint(
        vulnerabilities
    )

    if output_path.exists():
        try:
            existing = json.loads(
                output_path.read_text(
                    encoding="utf-8"
                )
            )

            existing_meta = existing.get(
                "meta",
                {},
            )

            existing_records = records_fingerprint(
                existing.get(
                    "vulnerabilities",
                    [],
                )
            )

            if (
                existing_meta.get("source") == "NVD"
                and existing_meta.get(
                    "reportingDate"
                ) == reporting_date
                and existing_records == new_records
            ):
                print(
                    f"Records unchanged for "
                    f"{reporting_date}; keeping existing "
                    "file (idempotent skip)."
                )
                return output_path

        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
        ):
            # Corrupt or structurally unusable existing file:
            # overwrite with a fresh valid snapshot.
            pass

    output = {
        "meta": {
            "source": "NVD",
            "collectedAt": utc_now().isoformat(),
            "reportingDate": reporting_date,
            "window": {
                "start": format_nvd_datetime(
                    start_date
                ),
                "end": format_nvd_datetime(
                    end_date
                ),
            },
            "count": len(vulnerabilities),
        },
        "vulnerabilities": vulnerabilities,
    }

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
        description=(
            "Collect CVEs for a TechPulse reporting "
            "day from the NVD API."
        )
    )

    parser.add_argument(
        "--date",
        type=str,
        help=(
            "Reporting date (YYYY-MM-DD, IST edition). "
            "Default: current reporting date."
        ),
    )

    parser.add_argument(
        "--start",
        type=str,
        help=(
            "Explicit ISO-8601 window start "
            "(overrides --date window)."
        ),
    )

    parser.add_argument(
        "--end",
        type=str,
        help=(
            "Explicit ISO-8601 window end "
            "(overrides --date window)."
        ),
    )

    args = parser.parse_args()

    try:
        start_date, end_date = resolve_window(
            args.date,
            args.start,
            args.end,
        )

        reporting_date = resolve_reporting_date(
            args.date,
            args.start,
            args.end,
            end_date,
        )

    except ValueError as exc:
        parser.error(str(exc))

    print()
    print("TechPulse — NVD Collector")
    print("=" * 32)
    print(
        f"Reporting date: {reporting_date} "
        "(IST edition)"
    )
    print(
        f"Window start  : "
        f"{format_nvd_datetime(start_date)}"
    )
    print(
        f"Window end    : "
        f"{format_nvd_datetime(end_date)}"
    )
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
            reporting_date=reporting_date,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print("Collection completed successfully.")
    print(
        f"Records : {len(vulnerabilities)}"
    )
    print(
        f"Output  : {output_path}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())