#!/usr/bin/env python3

"""
TechPulse — CISA KEV Collector

Collects the Known Exploited Vulnerabilities (KEV) catalog from CISA
and stores normalized JSON data for downstream processing.

Source:
    https://www.cisa.gov/known-exploited-vulnerabilities-catalog

Feed:
    https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json

Snapshot semantics:
    The KEV catalog is a full catalog snapshot, not a daily delta.
    A collected file records the catalog state at collection time for
    the target reporting date. Downstream processors derive "new KEV
    entries for the edition's covered India day" by matching the
    dateAdded calendar day.

Output:
    data/security/cisa/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with identical vulnerability records
    and identical catalog metadata does not rewrite the output file.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import ist_today, parse_ist_date  # noqa: E402


CATALOG_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

OUTPUT_DIR = PROJECT_ROOT / "data" / "security" / "cisa"

REQUEST_TIMEOUT = 30
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


def normalize_cve_id(value: Any) -> str | None:
    """Normalize and validate a CVE identifier."""
    if not isinstance(value, str):
        return None

    cve_id = value.strip().upper()

    if not CVE_ID_PATTERN.fullmatch(cve_id):
        return None

    return cve_id


def normalize_optional_string(value: Any) -> str | None:
    """Normalize optional text fields without inventing values."""
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def normalize_kev(
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a raw CISA KEV entry into TechPulse format."""

    if not isinstance(entry, dict):
        return None

    cve_id = normalize_cve_id(
        entry.get("cveID")
    )

    if cve_id is None:
        return None

    return {
        "cve_id": cve_id,
        "source": "CISA KEV",
        "vendor_project": normalize_optional_string(
            entry.get("vendorProject")
        ),
        "product": normalize_optional_string(
            entry.get("product")
        ),
        "vulnerability_name": normalize_optional_string(
            entry.get("vulnerabilityName")
        ),
        "date_added": normalize_optional_string(
            entry.get("dateAdded")
        ),
        "due_date": normalize_optional_string(
            entry.get("dueDate")
        ),
        "required_action": normalize_optional_string(
            entry.get("requiredAction")
        ),
        # CISA emits "Known" / "Unknown" strings.
        "known_ransomware_use": (
            entry.get("ransomwareCampaign") == "Known"
        ),
        "notes": normalize_optional_string(
            entry.get("notes")
        ),
        "cve_url": (
            "https://nvd.nist.gov/vuln/detail/"
            f"{cve_id}"
        ),
    }


def _retry_after_seconds(
    value: str | None,
) -> int | None:
    """Parse Retry-After as seconds or an HTTP date."""

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
            retry_at = retry_at.replace(
                tzinfo=timezone.utc
            )

        seconds = int(
            (
                retry_at.astimezone(timezone.utc)
                - utc_now()
            ).total_seconds()
        )

        return max(0, min(seconds, 120))

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _retry_delay_seconds(
    attempt: int,
    retry_after: str | None = None,
) -> int:
    """Calculate a bounded retry delay."""
    retry_after_seconds = _retry_after_seconds(
        retry_after
    )

    if retry_after_seconds is not None:
        return retry_after_seconds

    return RETRY_BACKOFF_BASE ** attempt * 2


def _read_response_body(response: Any) -> bytes:
    """Read a response while enforcing a maximum response size."""

    content_length = response.headers.get(
        "Content-Length"
    )

    if content_length:
        try:
            declared_size = int(content_length)

            if declared_size > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    "CISA KEV response is too large."
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
                "CISA KEV response exceeded the maximum "
                "allowed size."
            )

        chunks.append(chunk)

    return b"".join(chunks)


def _validate_catalog(
    data: Any,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Validate the minimum CISA KEV catalog structure required by
    downstream processing.
    """

    if not isinstance(data, dict):
        raise RuntimeError(
            "CISA KEV feed returned a response that is "
            "not a JSON object."
        )

    vulnerabilities = data.get("vulnerabilities")

    if not isinstance(vulnerabilities, list):
        raise RuntimeError(
            "CISA KEV feed field 'vulnerabilities' "
            "must be a list."
        )

    reported_count = data.get("count")

    if reported_count is not None:
        if (
            isinstance(reported_count, bool)
            or not isinstance(reported_count, int)
            or reported_count < 0
        ):
            raise RuntimeError(
                "CISA KEV feed returned an invalid "
                "'count' value."
            )

        if reported_count != len(vulnerabilities):
            raise RuntimeError(
                "CISA KEV feed 'count' does not match "
                "the number of vulnerabilities returned."
            )

    catalog_meta = {
        "catalog_version": normalize_optional_string(
            data.get("catalogVersion")
        ),
        "date_released": normalize_optional_string(
            data.get("dateReleased")
        ),
        "count_reported": reported_count,
    }

    return vulnerabilities, catalog_meta


def fetch_catalog() -> dict[str, Any]:
    """Fetch the CISA KEV catalog with conservative retries."""

    request = urllib.request.Request(
        CATALOG_URL,
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
            retry_after = getattr(
                fetch_catalog,
                "_retry_after",
                None,
            )

            wait = _retry_delay_seconds(
                attempt,
                retry_after,
            )

            print(
                f"  Retrying in {wait}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})..."
            )

            if wait > 0:
                time.sleep(wait)

            fetch_catalog._retry_after = None

        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                status = getattr(
                    response,
                    "status",
                    200,
                )
                raw = _read_response_body(response)

            if status == 429:
                print(
                    "  CISA feed rate limit hit (429)."
                )

                last_error = RuntimeError(
                    "CISA KEV feed returned HTTP 429 "
                    "(rate limited)."
                )

                continue

            if status != 200:
                last_error = RuntimeError(
                    f"CISA KEV feed returned HTTP {status}."
                )
                continue

            try:
                data = json.loads(
                    raw.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise RuntimeError(
                    "CISA KEV feed returned invalid JSON."
                ) from exc

            _validate_catalog(data)

            return data

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                print(
                    "  CISA feed rate limit hit (429)."
                )

                last_error = RuntimeError(
                    "CISA KEV feed returned HTTP 429 "
                    "(rate limited)."
                )

                fetch_catalog._retry_after = (
                    exc.headers.get("Retry-After")
                    if exc.headers
                    else None
                )

                continue

            if 500 <= exc.code < 600:
                print(
                    f"  CISA server error ({exc.code})."
                )

                last_error = RuntimeError(
                    f"CISA KEV feed returned HTTP "
                    f"{exc.code}: {exc.reason}"
                )

                continue

            raise RuntimeError(
                f"CISA KEV feed returned HTTP "
                f"{exc.code}: {exc.reason}"
            ) from exc

        except urllib.error.URLError as exc:
            print(
                f"  Network error reaching CISA: "
                f"{exc.reason}"
            )

            last_error = RuntimeError(
                f"Unable to reach CISA KEV feed: "
                f"{exc.reason}"
            )

            continue

        except TimeoutError:
            print("  CISA KEV request timed out.")

            last_error = RuntimeError(
                "CISA KEV request timed out."
            )

            continue

        except RuntimeError:
            raise

        except Exception as exc:
            print(
                f"  Unexpected error fetching "
                f"CISA KEV: {exc}"
            )

            last_error = RuntimeError(
                f"Unexpected CISA error: {exc}"
            )

            continue

    raise RuntimeError(
        f"CISA KEV request failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    ) from last_error


fetch_catalog._retry_after = None


def collect() -> list[dict[str, Any]]:
    """Collect and normalize the full CISA KEV catalog."""

    # Never allow catalog metadata from a previous successful
    # invocation to survive into a subsequent collection.
    collect.catalog_meta = {}

    print("Fetching CISA KEV catalog...")

    data = fetch_catalog()

    entries, catalog_meta = _validate_catalog(
        data
    )

    print(
        f"Received {len(entries)} KEV entries"
    )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    malformed = 0

    for entry in entries:
        record = normalize_kev(entry)

        if record is None:
            malformed += 1
            continue

        cve_id = record["cve_id"]

        if cve_id in seen:
            continue

        seen.add(cve_id)
        normalized.append(record)

    if malformed:
        print(
            f"Skipped {malformed} malformed KEV entries "
            "(missing or invalid cveID)."
        )

    # Preserve information needed by save_output and processors.
    catalog_meta["malformed_entries"] = malformed
    catalog_meta["normalized_count"] = len(
        normalized
    )

    # Deterministic ordering: CVE ID ascending.
    normalized.sort(
        key=lambda v: v["cve_id"]
    )

    collect.catalog_meta = catalog_meta

    return normalized


collect.catalog_meta = {}


def records_fingerprint(
    vulnerabilities: list[dict[str, Any]],
) -> str:
    """Return a stable fingerprint of vulnerability records."""
    return json.dumps(
        vulnerabilities,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def metadata_fingerprint(
    metadata: dict[str, Any],
) -> str:
    """Return a stable fingerprint of catalog metadata."""
    return json.dumps(
        metadata,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def save_output(
    vulnerabilities: list[dict[str, Any]],
    snapshot_date: str,
) -> Path:
    """Save the catalog snapshot idempotently."""

    if parse_ist_date(snapshot_date) is None:
        raise ValueError(
            "snapshot_date must be in YYYY-MM-DD format."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / f"{snapshot_date}.json"
    )

    new_records = records_fingerprint(
        vulnerabilities
    )

    catalog_meta = getattr(
        collect,
        "catalog_meta",
        {},
    )

    new_catalog_meta = metadata_fingerprint(
        catalog_meta
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

            existing_catalog_meta = (
                existing_meta.get(
                    "catalog",
                    {},
                )
            )

            if (
                existing_records == new_records
                and existing_meta.get(
                    "source"
                ) == "CISA KEV"
                and existing_meta.get(
                    "reportingDate"
                ) == snapshot_date
                and metadata_fingerprint(
                    existing_catalog_meta
                ) == new_catalog_meta
            ):
                print(
                    f"Catalog and metadata unchanged "
                    f"for {snapshot_date}; keeping "
                    "existing file (idempotent skip)."
                )
                return output_path

        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
        ):
            # Corrupt or structurally unusable existing
            # snapshot: overwrite with fresh data.
            pass

    output = {
        "meta": {
            "source": "CISA KEV",
            "collectedAt": utc_now().isoformat(),
            "reportingDate": snapshot_date,
            "catalog": catalog_meta,
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
            "Collect the CISA Known Exploited "
            "Vulnerabilities catalog."
        )
    )

    parser.add_argument(
        "--date",
        type=str,
        help=(
            "Reporting date label (YYYY-MM-DD, "
            "IST edition). Default: current "
            "reporting date."
        ),
    )

    args = parser.parse_args()

    if args.date:
        if parse_ist_date(args.date) is None:
            parser.error(
                "--date must be in YYYY-MM-DD format."
            )

        snapshot_date = args.date
    else:
        snapshot_date = ist_today()

    print()
    print("TechPulse — CISA KEV Collector")
    print("=" * 32)
    print(
        f"Reporting date: {snapshot_date} "
        "(IST edition)"
    )
    print()

    try:
        vulnerabilities = collect()

        output_path = save_output(
            vulnerabilities,
            snapshot_date,
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
