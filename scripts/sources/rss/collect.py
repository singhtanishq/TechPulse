#!/usr/bin/env python3

"""
TechPulse — RSS/Atom Collector

Collects technology news and updates from configured RSS/Atom feeds.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse various datetime formats from RSS/Atom feeds."""
    if not value:
        return None
    value = value.strip()
    # Try common formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",      # RFC 822 with timezone name
        "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 UTC
        "%Y-%m-%dT%H:%M:%S.%f%z",        # ISO 8601 with microseconds
        "%Y-%m-%dT%H:%M:%S.%fZ",         # ISO 8601 UTC with microseconds
        "%Y-%m-%d %H:%M:%S%z",           # Space separator
        "%Y-%m-%d %H:%M:%S",             # No timezone
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


def clean_html(text: str | None) -> str:
    """Strip HTML tags and decode entities."""
    if not text:
        return ""
    # Simple tag removal
    import re
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_feed_with_retry(url: str) -> bytes | None:
    """Fetch a feed URL with retry logic."""
    headers = {
        "User-Agent": "TechPulse/1.0 (RSS Collector)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")

    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                status = response.status
                if status == 429:
                    wait_time = 30 * (attempt + 1)
                    print(f"  Rate limited (429). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                if 500 <= status < 600:
                    wait_time = RETRY_BACKOFF_BASE ** attempt
                    print(f"  Server error ({status}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                if status != 200:
                    raise RuntimeError(f"Feed returned HTTP {status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"  Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            if 500 <= exc.code < 600:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                print(f"  Server error ({exc.code}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            print(f"  HTTP error {exc.code}: {exc.reason}")
            return None
        except urllib.error.URLError as exc:
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(f"  Network error: {exc.reason}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            last_exception = exc
            continue
        except Exception as exc:
            last_exception = exc
            wait_time = RETRY_BACKOFF_BASE ** attempt
            print(f"  Unexpected error: {exc}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

    print(f"  Failed after {MAX_RETRIES} attempts")
    return None


def parse_rss(content: bytes, feed_url: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 feed."""
    entries = []
    try:
        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is None:
            return entries

        for item in channel.findall("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            description = clean_html(item.findtext("description"))
            pub_date = parse_datetime(item.findtext("pubDate"))
            guid = item.findtext("guid", "").strip()

            # Use guid as fallback for link
            if not link and guid:
                link = guid

            # Validate URL
            if link and not is_valid_url(link):
                link = ""

            entries.append({
                "title": title,
                "url": link,
                "summary": description,
                "published_at": pub_date.isoformat() if pub_date else None,
                "guid": guid or link,
                "feed_url": feed_url,
            })
    except ET.ParseError:
        pass
    return entries


def parse_atom(content: bytes, feed_url: str) -> list[dict[str, Any]]:
    """Parse Atom 1.0 feed."""
    entries = []
    # Atom namespace
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(content)
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", "", ns) or "").strip()
            link = ""
            link_elem = entry.find("atom:link", ns)
            if link_elem is not None:
                link = (link_elem.get("href") or "").strip()
            summary = clean_html(entry.findtext("atom:summary", "", ns) or
                                 entry.findtext("atom:content", "", ns))
            pub_date = parse_datetime(entry.findtext("atom:published", "", ns) or
                                       entry.findtext("atom:updated", "", ns))
            guid = (entry.findtext("atom:id", "", ns) or "").strip()

            if not link and guid:
                link = guid

            if link and not is_valid_url(link):
                link = ""

            entries.append({
                "title": title,
                "url": link,
                "summary": summary,
                "published_at": pub_date.isoformat() if pub_date else None,
                "guid": guid or link,
                "feed_url": feed_url,
            })
    except ET.ParseError:
        pass
    return entries


def is_valid_url(url: str) -> bool:
    """Basic URL validation."""
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def detect_feed_type(content: bytes) -> str:
    """Detect if feed is RSS or Atom."""
    try:
        root = ET.fromstring(content)
        if root.tag.endswith("rss") or root.tag == "rss":
            return "rss"
        if root.tag.endswith("feed") or "feed" in root.tag.lower():
            return "atom"
        # Check for Atom namespace
        if "http://www.w3.org/2005/Atom" in ET.tostring(root, encoding="unicode")[:500]:
            return "atom"
    except ET.ParseError:
        pass
    return "rss"  # default


def collect() -> list[dict[str, Any]]:
    """Collect entries from all configured feeds."""
    config = load_config()
    feeds = config.get("feeds", [])
    collection_config = config.get("collection", {})
    max_entries = collection_config.get("max_entries_per_feed", 50)
    delay = collection_config.get("rate_limit_delay_seconds", 2)

    all_entries = []
    seen_guids: set[str] = set()

    for feed in feeds:
        name = feed.get("name", "Unknown")
        url = feed.get("url")
        category = feed.get("category", "tech")
        source = feed.get("source", "Unknown")

        if not url:
            print(f"Skipping {name}: no URL")
            continue

        print(f"Fetching {name} ({url})...")
        content = fetch_feed_with_retry(url)
        if not content:
            print(f"  Failed to fetch")
            continue

        feed_type = detect_feed_type(content)
        print(f"  Detected {feed_type.upper()} feed")

        if feed_type == "atom":
            entries = parse_atom(content, url)
        else:
            entries = parse_rss(content, url)

        # Add feed metadata to each entry
        for entry in entries:
            entry["feed_name"] = name
            entry["feed_category"] = category
            entry["feed_source"] = source
            entry["source"] = "RSS"
            entry["collected_at"] = utc_now().isoformat()

        # Deduplicate by GUID
        feed_entries = []
        for entry in entries:
            guid = entry.get("guid") or entry.get("url")
            if guid and guid not in seen_guids:
                seen_guids.add(guid)
                feed_entries.append(entry)

        # Limit entries per feed
        feed_entries = feed_entries[:max_entries]
        all_entries.extend(feed_entries)

        print(f"  Collected {len(feed_entries)} entries")
        time.sleep(delay)

    # Deterministic sort: by published date descending, then URL
    all_entries.sort(
        key=lambda e: (e.get("published_at", "") or "", e.get("url", "")),
        reverse=True
    )

    return all_entries


def save_output(entries: list[dict[str, Any]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    collection_date = utc_now().date().isoformat()
    output = {
        "meta": {
            "source": "RSS",
            "collectedAt": utc_now().isoformat(),
            "count": len(entries),
        },
        "entries": entries,
    }
    output_path = OUTPUT_DIR / f"{collection_date}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect technology updates from RSS/Atom feeds.")
    args = parser.parse_args()

    print()
    print("TechPulse — RSS/Atom Collector")
    print("=" * 32)
    print()

    try:
        entries = collect()
        output_path = save_output(entries)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Collection completed successfully.")
    print(f"Entries   : {len(entries)}")
    print(f"Output    : {output_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())