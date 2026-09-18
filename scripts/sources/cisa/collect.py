#!/usr/bin/env python3

"""
TechPulse — CISA KEV Collector

Collects the Known Exploited Vulnerabilities (KEV) catalog
from CISA and stores normalized JSON data for downstream processing.

Source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
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
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime string."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def normalize_kev(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw CISA KEV entry into TechPulse format."""
    return {
        "cve_id": entry.get("cveID"),
        "source": "CISA KEV",
        "vendor_project": entry.get("vendorProject"),
        "product": entry.get("product"),
        "vulnerability_name": entry.get("vulnerabilityName"),
        "date_added": entry.get("dateAdded"),
        "due_date": entry.get("dueDate"),
        "required_action": entry.get("requiredAction"),
        "ransomware_known": entry.get("ransomwareCampaign", False),
        "notes": entry.get("notes"),
        "cve_url": f"https://nvd.nist.gov/vuln/detail/{entry.get('cveID')}" if entry.get("cveID") else None,
    }


def fetch_catalog_with_retry() -> dict[str, Any]:
    """Fetch the CISA KEV catalog with retry logic."""
    request = urllib.request.Request(
        CATALOG_URL,
        headers={
            "User-Agent": "TechPulse/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                status = response.status
                if status == 429:
                    wait_time = 30 * (attempt + 1)
                    print(f"Rate limited (429). Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                if status != 200:
                    raise RuntimeError(f"CISA KEV API returned unexpected HTTP status {status}")
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"Rate limited (429). Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            if 500 <= exc.code < 600:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                print(f"Server error ({exc.code}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            raise RuntimeError(f"CISA KEV API returned HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(f"Network error: {exc.reason}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            last_exception = exc
            continue
        except Exception as exc:
            last_exception = exc
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(f"Unexpected error: {exc}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("CISA KEV API returned invalid JSON.") from exc

    if last_exception:
        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {last_exception}") from last_exception
    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")


def collect() -> list[dict[str, Any]]:
    """Collect and normalize CISA KEV entries."""
    print("Fetching CISA KEV catalog...")
    data = fetch_catalog_with_retry()

    vulnerabilities = data.get("vulnerabilities", [])
    print(f"Received {len(vulnerabilities)} KEV entries")

    normalized = []
    seen_ids: set[str] = set()

    for entry in vulnerabilities:
        normalized_entry = normalize_kev(entry)
        cve_id = normalized_entry.get("cve_id")
        if cve_id and cve_id not in seen_ids:
            seen_ids.add(cve_id)
            normalized.append(normalized_entry)

    # Deterministic sort: by CVE ID ascending
    normalized.sort(key=lambda v: v.get("cve_id", ""))

    return normalized


def save_output(vulnerabilities: list[dict[str, Any]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    collection_date = utc_now().date().isoformat()

    output = {
        "meta": {
            "source": "CISA KEV",
            "collectedAt": utc_now().isoformat(),
            "count": len(vulnerabilities),
        },
        "vulnerabilities": vulnerabilities,
    }

    output_path = OUTPUT_DIR / f"{collection_date}.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False, sort_keys=True)
        file.write("\n")

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect CISA Known Exploited Vulnerabilities catalog.")
    args = parser.parse_args()

    print()
    print("TechPulse — CISA KEV Collector")
    print("=" * 32)
    print()

    try:
        vulnerabilities = collect()
        output_path = save_output(vulnerabilities)
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