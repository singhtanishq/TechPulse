#!/usr/bin/env python3

"""
TechPulse — CISA KEV Collector

Collects the Known Exploited Vulnerabilities (KEV) catalog from CISA
and stores normalized JSON data for downstream processing.

Source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
Feed:   https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json

Note on semantics:
    The KEV catalog is a full catalog snapshot, not a daily delta.
    A collected file records the catalog state at collection time for
    the target snapshot date. Downstream processors derive "new KEV
    entries for date X" by comparing dateAdded fields.

Output:
    data/security/cisa/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with an identical catalog does not
    rewrite the output file.
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
import urllib.request


CATALOG_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

PROJECT_ROOT = Path(__file__).resolve().parents[3]

OUTPUT_DIR = PROJECT_ROOT / "data" / "security" / "cisa"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_snapshot_date() -> datetime:
    yesterday = (utc_now() - timedelta(days=1)).date()
    return datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)


def normalize_kev(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw CISA KEV entry into TechPulse format."""

    cve_id = entry.get("cveID")

    if not cve_id:
        return None

    return {
        "cve_id": cve_id,
        "source": "CISA KEV",
        "vendor_project": entry.get("vendorProject"),
        "product": entry.get("product"),
        "vulnerability_name": entry.get("vulnerabilityName"),
        "date_added": entry.get("dateAdded"),
        "due_date": entry.get("dueDate"),
        "required_action": entry.get("requiredAction"),
        # CISA emits "Known" / "Unknown" strings.
        "known_ransomware_use": entry.get("ransomwareCampaign") == "Known",
        "notes": entry.get("notes"),
        "cve_url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
    }


def fetch_catalog() -> dict[str, Any]:
    """Fetch the CISA KEV catalog with conservative retries."""

    request = urllib.request.Request(
        CATALOG_URL,
        headers={
            "User-Agent": "TechPulse/1.0 (+https://github.com/singhtanishq/TechPulse)",
            "Accept": "application/json",
        },
        method="GET",
    )

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):

        if attempt > 0:
            wait = RETRY_BACKOFF_BASE ** attempt * 2
            print(f"  Retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read()

            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("CISA KEV feed returned invalid JSON.") from exc

            if "vulnerabilities" not in data:
                raise RuntimeError("CISA KEV feed missing 'vulnerabilities' key.")

            return data

        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600 or exc.code == 429:
                print(f"  CISA feed HTTP {exc.code}.")
                last_error = RuntimeError(f"CISA KEV feed returned HTTP {exc.code}")
                continue
            raise RuntimeError(f"CISA KEV feed returned HTTP {exc.code}: {exc.reason}") from exc

        except urllib.error.URLError as exc:
            print(f"  Network error reaching CISA: {exc.reason}")
            last_error = RuntimeError(f"Unable to reach CISA KEV feed: {exc.reason}")
            continue

        except RuntimeError:
            raise

        except Exception as exc:
            print(f"  Unexpected error fetching CISA KEV: {exc}")
            last_error = RuntimeError(f"Unexpected CISA error: {exc}")
            continue

    raise RuntimeError(
        f"CISA KEV request failed after {MAX_RETRIES} attempts: {last_error}"
    ) from last_error


def collect() -> list[dict[str, Any]]:
    """Collect and normalize the KEV catalog."""

    print("Fetching CISA KEV catalog...")
    data = fetch_catalog()

    catalog_meta = {
        "catalog_version": data.get("catalogVersion"),
        "date_released": data.get("dateReleased"),
        "count_reported": data.get("count"),
    }

    entries = data.get("vulnerabilities", [])
    print(f"Received {len(entries)} KEV entries")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    malformed = 0
    for entry in entries:
        record = normalize_kev(entry)
        if record is None:
            malformed += 1
            continue
        if record["cve_id"] not in seen:
            seen.add(record["cve_id"])
            normalized.append(record)

    if malformed:
        print(f"Skipped {malformed} malformed KEV entries (missing cveID).")

    # Deterministic ordering: CVE ID ascending.
    normalized.sort(key=lambda v: v["cve_id"])

    # Stash catalog metadata on the first pass via a module-level return pair.
    collect.catalog_meta = catalog_meta  # type: ignore[attr-defined]

    return normalized


def records_fingerprint(vulnerabilities: list[dict[str, Any]]) -> str:
    return json.dumps(vulnerabilities, sort_keys=True, ensure_ascii=False)


def save_output(vulnerabilities: list[dict[str, Any]], snapshot_date: str) -> Path:
    """Save the catalog snapshot idempotently for the target date."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"{snapshot_date}.json"

    new_records = records_fingerprint(vulnerabilities)

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            existing_records = records_fingerprint(existing.get("vulnerabilities", []))
            if existing_records == new_records:
                print(
                    f"Catalog unchanged for {snapshot_date}; "
                    f"keeping existing file (idempotent skip)."
                )
                return output_path
        except (json.JSONDecodeError, OSError):
            pass

    catalog_meta = getattr(collect, "catalog_meta", {})

    output = {
        "meta": {
            "source": "CISA KEV",
            "collectedAt": utc_now().isoformat(),
            "snapshotDate": snapshot_date,
            "catalog": catalog_meta,
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
        description="Collect the CISA Known Exploited Vulnerabilities catalog."
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Snapshot date label (YYYY-MM-DD, UTC). Default: previous completed UTC day.",
    )
    args = parser.parse_args()

    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
            snapshot_date = args.date
        except ValueError:
            parser.error("--date must be in YYYY-MM-DD format.")
    else:
        snapshot_date = default_snapshot_date().date().isoformat()

    print()
    print("TechPulse — CISA KEV Collector")
    print("=" * 32)
    print(f"Snapshot date : {snapshot_date}")
    print()

    try:
        vulnerabilities = collect()
        output_path = save_output(vulnerabilities, snapshot_date)
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
