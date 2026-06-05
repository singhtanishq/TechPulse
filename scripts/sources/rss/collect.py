#!/usr/bin/env python3

"""
TechPulse — RSS/Atom Collector

Collects technology news and updates from configured RSS 2.0 and
Atom 1.0 feeds.

Design notes:
    - Each feed is collected independently; one failing feed never
      aborts the run or discards other feeds' data.
    - Entries store title, source, URL, publication date and a short
      excerpt only. Full article bodies are intentionally not stored
      (copyright safety); TechPulse links to the original publisher.
    - Deduplication uses the feed GUID, falling back to the URL.

Output:
    data/tech/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with identical entries does not
    rewrite the output file.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "scripts" / "config" / "rss.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "tech"

DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
SUMMARY_MAX_CHARS = 300

ATOM_NS = "http://www.w3.org/2005/Atom"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_snapshot_date() -> str:
    yesterday = (utc_now() - timedelta(days=1)).date()
    return yesterday.isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common RSS/Atom date formats into aware UTC datetimes."""
    if not value:
        return None
    value = value.strip()

    # Normalize obsolete zone names used in some feeds.
    value = re.sub(
        r"\b(UT|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b",
        lambda m: {
            "UT": "+0000", "GMT": "+0000",
            "EST": "-0500", "EDT": "-0400",
            "CST": "-0600", "CDT": "-0500",
            "MST": "-0700", "MDT": "-0600",
            "PST": "-0800", "PDT": "-0700",
        }[m.group(1)],
        value,
    )

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",       # RFC 822 (RSS 2.0)
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",            # ISO 8601 (Atom)
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",              # No timezone -> assume UTC below
        "%Y-%m-%d",                       # Date only
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def clean_text(text: str | None) -> str:
    """Strip HTML tags and decode entities into plain text."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """Shorten text to an excerpt (copyright safety: no full bodies)."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def is_valid_url(url: str) -> bool:
    """Only http/https URLs with a host are accepted."""
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_feed(url: str) -> bytes | None:
    """Fetch a feed with retries. Returns None on permanent failure."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TechPulse/1.0 (+https://github.com/singhtanishq/TechPulse)",
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, */*"
            ),
        },
        method="GET",
    )

    for attempt in range(MAX_RETRIES):

        if attempt > 0:
            wait = RETRY_BACKOFF_BASE ** attempt * 2
            print(f"    Retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)

        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                if response.status != 200:
                    print(f"    Feed returned HTTP {response.status}.")
                    continue
                return response.read()

        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600 or exc.code == 429:
                print(f"    Feed HTTP {exc.code}.")
                continue
            print(f"    Feed HTTP {exc.code}: {exc.reason}. Giving up on this feed.")
            return None

        except urllib.error.URLError as exc:
            print(f"    Network error: {exc.reason}.")
            continue

        except Exception as exc:
            print(f"    Unexpected error: {exc}.")
            continue

    return None


def normalize_entry(
    title: str,
    link: str,
    summary: str,
    published: datetime | None,
    guid: str,
    feed: dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize a single entry; returns None if structurally unusable."""

    title = clean_text(title)
    link = (link or guid or "").strip()

    if not title and not link:
        return None

    if link and not is_valid_url(link):
        link = ""

    return {
        "title": title or "(untitled)",
        "url": link,
        "summary": truncate(clean_text(summary)),
        "published_at": published.isoformat() if published else None,
        "guid": guid or link or title,
        "feed_url": feed.get("url", ""),
        "feed_name": feed.get("name", "Unknown"),
        "feed_category": feed.get("category", "tech"),
        "feed_source": feed.get("source", "Unknown"),
        "source": "RSS",
    }


def parse_feed(content: bytes, feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom 1.0 content into normalized entries."""

    entries: list[dict[str, Any]] = []

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        print("    Malformed XML; giving up on this feed.")
        return entries

    is_atom = root.tag == f"{{{ATOM_NS}}}feed" or root.tag == "feed"

    if is_atom:
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            title = entry.findtext(f"{{{ATOM_NS}}}title", "")
            link = ""
            for link_elem in entry.findall(f"{{{ATOM_NS}}}link"):
                rel = link_elem.get("rel", "alternate")
                if rel == "alternate" or link_elem.get("href"):
                    link = link_elem.get("href", "")
                    if rel == "alternate":
                        break
            summary = (
                entry.findtext(f"{{{ATOM_NS}}}summary", "")
                or entry.findtext(f"{{{ATOM_NS}}}content", "")
            )
            published_raw = (
                entry.findtext(f"{{{ATOM_NS}}}published")
                or entry.findtext(f"{{{ATOM_NS}}}updated")
            )
            guid = entry.findtext(f"{{{ATOM_NS}}}id", "")
            published = parse_datetime(published_raw)

            record = normalize_entry(title, link, summary, published, guid, feed)
            if record:
                entries.append(record)
    else:
        channel = root.find("channel")
        if channel is None:
            print("    RSS feed missing <channel>; giving up on this feed.")
            return entries

        for item in channel.findall("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            summary = item.findtext("description", "")
            published = parse_datetime(item.findtext("pubDate"))
            guid = item.findtext("guid", "")

            record = normalize_entry(title, link, summary, published, guid, feed)
            if record:
                entries.append(record)

    return entries


def collect() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Collect entries from all configured feeds."""

    config = load_config()
    feeds = config.get("feeds", [])
    collection_config = config.get("collection", {})
    max_entries = collection_config.get("max_entries_per_feed", 50)
    delay = collection_config.get("rate_limit_delay_seconds", 2)

    all_entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_guids: set[str] = set()

    for feed in feeds:
        name = feed.get("name", "Unknown")
        url = feed.get("url")
        source = feed.get("source", "Unknown")

        if not url:
            failures.append({"feed": name, "error": "No URL configured"})
            continue

        print(f"Fetching {name} ({source})...")

        content = fetch_feed(url)
        if content is None:
            failures.append({"feed": name, "error": "Fetch failed after retries"})
            continue

        entries = parse_feed(content, feed)

        if not entries:
            failures.append({"feed": name, "error": "No parseable entries"})
            continue

        added = 0
        for entry in entries:
            key = entry["guid"] or entry["url"]
            if key and key not in seen_guids:
                seen_guids.add(key)
                all_entries.append(entry)
                added += 1
                if added >= max_entries:
                    break

        print(f"    Collected {added} entries")

        if delay > 0:
            time.sleep(delay)

    # Deterministic ordering: publication date descending, then URL, then title.
    all_entries.sort(
        key=lambda e: (e.get("published_at") or "", e.get("url") or "", e.get("title") or ""),
        reverse=True,
    )

    return all_entries, failures


def records_fingerprint(entries: list[dict[str, Any]]) -> str:
    return json.dumps(entries, sort_keys=True, ensure_ascii=False)


def save_output(entries: list[dict[str, Any]], failures: list[dict[str, str]], snapshot_date: str) -> Path:
    """Save entries idempotently for the target date."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"{snapshot_date}.json"

    new_records = records_fingerprint(entries)

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if records_fingerprint(existing.get("entries", [])) == new_records:
                print(f"Entries unchanged for {snapshot_date}; keeping existing file.")
                return output_path
        except (json.JSONDecodeError, OSError):
            pass

    output = {
        "meta": {
            "source": "RSS",
            "collectedAt": utc_now().isoformat(),
            "snapshotDate": snapshot_date,
            "count": len(entries),
            "failures": failures,
        },
        "entries": entries,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")

    return output_path


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Collect technology updates from RSS/Atom feeds."
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
        snapshot_date = default_snapshot_date()

    print()
    print("TechPulse — RSS/Atom Collector")
    print("=" * 32)
    print(f"Snapshot date : {snapshot_date}")
    print()

    try:
        entries, failures = collect()
        output_path = save_output(entries, failures, snapshot_date)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Collection finished.")
    print(f"Entries : {len(entries)}")
    if failures:
        print(f"Feed failures: {len(failures)}")
        for failure in failures:
            print(f"  - {failure['feed']}: {failure['error']}")
    print(f"Output  : {output_path}")
    print()

    # Exit 0 unless nothing at all was collected from any feed.
    if not entries:
        print("ERROR: No RSS entries could be collected.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
