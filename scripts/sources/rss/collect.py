#!/usr/bin/env python3

"""
TechPulse — RSS/Atom Collector

Collects technology news and updates from configured RSS 2.0 and
Atom 1.0 feeds.

Design notes:
    - Each feed is collected independently; one failing feed never
      aborts the run or discards other feeds' data.
    - A healthy feed with zero entries is valid and is NOT recorded as
      a failure.
    - Malformed XML, structurally invalid feeds, invalid feed URLs,
      and fetch failures are recorded as failures.
    - Entries store title, source, URL, publication date and a short
      excerpt only. Full article bodies are intentionally not stored
      (copyright safety); TechPulse links to the original publisher.
    - Deduplication is snapshot-global by entry identity (GUID, then
      URL, then title). Publishers commonly syndicate the same story
      through several feeds (for example a general technology feed and
      a dedicated security feed); a story must appear once per edition
      regardless of how many configured feeds carried it. Unrelated
      articles never collide because their identities differ.
    - Publication timestamps are normalized to UTC when possible.

Output:
    data/tech/YYYY-MM-DD.json

Idempotency:
    Re-running for the same date with identical entries and identical
    failure metadata does not rewrite the output file.
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import urllib.error
import urllib.request

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import ist_today, parse_ist_date  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "scripts" / "config" / "rss.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "tech"

DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
SUMMARY_MAX_CHARS = 300
MAX_FEED_BYTES = 10 * 1024 * 1024

ATOM_NS = "http://www.w3.org/2005/Atom"


class FeedParseError(Exception):
    """Raised when a feed cannot be structurally parsed."""


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common RSS/Atom date formats into an aware UTC datetime."""
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    # Normalize obsolete timezone names used by some feeds.
    value = re.sub(
        r"\b(UT|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b",
        lambda m: {
            "UT": "+0000",
            "GMT": "+0000",
            "EST": "-0500",
            "EDT": "-0400",
            "CST": "-0600",
            "CDT": "-0500",
            "MST": "-0700",
            "MDT": "-0600",
            "PST": "-0800",
            "PDT": "-0700",
        }[m.group(1)],
        value,
    )

    # First handle RFC-style dates through the standard library parser.
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass

    # Then handle ISO 8601 variants.
    iso_value = value
    if iso_value.endswith("Z"):
        iso_value = iso_value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(iso_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
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


def element_text(element: ET.Element | None) -> str:
    """Return normalized text from an XML element, including nested nodes."""
    if element is None:
        return ""

    text = "".join(element.itertext())
    return clean_text(text)


def truncate(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """Shorten text to an excerpt (copyright safety: no full bodies)."""
    if len(text) <= limit:
        return text

    truncated = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:")
    return truncated + "…"


def is_valid_url(url: str) -> bool:
    """Only http/https URLs with a host are accepted."""
    if not url:
        return False

    try:
        result = urlparse(url.strip())
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def load_config() -> dict[str, Any]:
    """Load and validate the RSS configuration file."""
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if not isinstance(config, dict):
        raise ValueError("RSS configuration must be a JSON object.")

    feeds = config.get("feeds", [])
    if not isinstance(feeds, list):
        raise ValueError("RSS configuration field 'feeds' must be a list.")

    return config


def retry_delay(attempt: int, retry_after: str | None = None) -> int:
    """Return a bounded retry delay, honoring Retry-After when possible."""
    if retry_after:
        try:
            seconds = int(retry_after.strip())
            if seconds >= 0:
                return min(seconds, 60)
        except ValueError:
            try:
                retry_date = email.utils.parsedate_to_datetime(retry_after)
                if retry_date is not None:
                    if retry_date.tzinfo is None:
                        retry_date = retry_date.replace(tzinfo=timezone.utc)

                    delta = retry_date.astimezone(timezone.utc) - datetime.now(timezone.utc)
                    seconds = max(0, int(delta.total_seconds()))
                    return min(seconds, 60)
            except (TypeError, ValueError, OverflowError):
                pass

    return RETRY_BACKOFF_BASE ** attempt * 2


def fetch_feed(url: str) -> bytes | None:
    """Fetch a feed with retries. Returns None on permanent failure."""

    if not is_valid_url(url):
        print("    Invalid feed URL; only HTTP/HTTPS URLs are allowed.")
        return None

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "TechPulse/1.0 "
                "(+https://github.com/singhtanishq/TechPulse)"
            ),
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, */*"
            ),
        },
        method="GET",
    )

    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait = retry_delay(attempt)
            print(
                f"    Retrying in {wait}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})..."
            )
            time.sleep(wait)

        try:
            with urllib.request.urlopen(
                request,
                timeout=DEFAULT_TIMEOUT,
            ) as response:
                status = getattr(response, "status", 200)

                if status != 200:
                    print(f"    Feed returned HTTP {status}.")
                    continue

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                        if declared_size > MAX_FEED_BYTES:
                            print(
                                f"    Feed is too large "
                                f"({declared_size} bytes > {MAX_FEED_BYTES})."
                            )
                            return None
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total_size = 0

                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break

                    total_size += len(chunk)
                    if total_size > MAX_FEED_BYTES:
                        print(
                            f"    Feed exceeded maximum size "
                            f"({MAX_FEED_BYTES} bytes)."
                        )
                        return None

                    chunks.append(chunk)

                return b"".join(chunks)

        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600 or exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None

                if retry_after:
                    try:
                        wait = retry_delay(attempt, retry_after)
                        print(f"    Feed HTTP {exc.code}; retrying in {wait}s.")
                    except Exception:
                        print(f"    Feed HTTP {exc.code}.")
                else:
                    print(f"    Feed HTTP {exc.code}.")

                continue

            print(
                f"    Feed HTTP {exc.code}: {exc.reason}. "
                "Giving up on this feed."
            )
            return None

        except urllib.error.URLError as exc:
            print(f"    Network error: {exc.reason}.")
            continue

        except TimeoutError:
            print("    Feed request timed out.")
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
    link = (link or "").strip()
    guid = clean_text(guid)

    if link and not is_valid_url(link):
        link = ""

    # Entries with neither a real title nor a usable URL are junk.
    if not title and not link:
        return None

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


def atom_entry_elements(root: ET.Element) -> list[ET.Element]:
    """Return Atom entry elements for both namespaced and non-namespaced feeds."""
    entries = root.findall(f"{{{ATOM_NS}}}entry")

    if not entries:
        entries = [
            child
            for child in root
            if child.tag.split("}")[-1] == "entry"
        ]

    return entries


def find_child(element: ET.Element, name: str) -> ET.Element | None:
    """Find a direct child by local XML name, regardless of namespace."""
    for child in element:
        if child.tag.split("}")[-1] == name:
            return child
    return None


def find_children(element: ET.Element, name: str) -> list[ET.Element]:
    """Find direct children by local XML name, regardless of namespace."""
    return [
        child
        for child in element
        if child.tag.split("}")[-1] == name
    ]


def parse_feed(content: bytes, feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom 1.0 content into normalized entries."""

    if not content:
        raise FeedParseError("Feed returned an empty response body.")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FeedParseError(f"Malformed XML: {exc}") from exc

    root_name = root.tag.split("}")[-1].lower()

    entries: list[dict[str, Any]] = []

    if root_name == "feed":
        raw_entries = atom_entry_elements(root)

        # A valid Atom feed is allowed to contain zero entries.
        for entry in raw_entries:
            title = element_text(find_child(entry, "title"))

            link = ""
            link_elements = find_children(entry, "link")

            # Prefer rel="alternate".
            for link_elem in link_elements:
                href = (link_elem.get("href") or "").strip()
                rel = (link_elem.get("rel") or "alternate").strip().lower()

                if href and rel == "alternate":
                    link = href
                    break

            # Otherwise use the first href available.
            if not link:
                for link_elem in link_elements:
                    href = (link_elem.get("href") or "").strip()
                    if href:
                        link = href
                        break

            summary = element_text(find_child(entry, "summary"))
            if not summary:
                summary = element_text(find_child(entry, "content"))

            published_raw = element_text(find_child(entry, "published"))
            if not published_raw:
                published_raw = element_text(find_child(entry, "updated"))

            guid = element_text(find_child(entry, "id"))
            published = parse_datetime(published_raw)

            record = normalize_entry(
                title,
                link,
                summary,
                published,
                guid,
                feed,
            )

            if record:
                entries.append(record)

        if raw_entries and not entries:
            raise FeedParseError(
                "Atom feed contained entries, but none were usable."
            )

        return entries

    if root_name in {"rss", "rdf", "rdf:rdf"}:
        channel = find_child(root, "channel")

        if channel is None and root_name == "rss":
            raise FeedParseError("RSS feed missing <channel>.")

        if channel is not None:
            raw_items = find_children(channel, "item")

            for item in raw_items:
                title = element_text(find_child(item, "title"))
                link = element_text(find_child(item, "link"))
                summary = element_text(find_child(item, "description"))

                published_raw = element_text(find_child(item, "pubDate"))

                if not published_raw:
                    published_raw = element_text(find_child(item, "published"))

                guid = element_text(find_child(item, "guid"))
                published = parse_datetime(published_raw)

                record = normalize_entry(
                    title,
                    link,
                    summary,
                    published,
                    guid,
                    feed,
                )

                if record:
                    entries.append(record)

            if raw_items and not entries:
                raise FeedParseError(
                    "RSS feed contained items, but none were usable."
                )

            return entries

        # RDF-style feeds commonly use <item> directly under the root.
        raw_items = find_children(root, "item")

        for item in raw_items:
            title = element_text(find_child(item, "title"))
            link = element_text(find_child(item, "link"))
            summary = element_text(
                find_child(item, "description")
                or find_child(item, "summary")
            )

            published_raw = element_text(find_child(item, "pubDate"))
            if not published_raw:
                published_raw = element_text(find_child(item, "published"))

            guid = element_text(find_child(item, "guid"))
            published = parse_datetime(published_raw)

            record = normalize_entry(
                title,
                link,
                summary,
                published,
                guid,
                feed,
            )

            if record:
                entries.append(record)

        if raw_items and not entries:
            raise FeedParseError(
                "RSS/RDF feed contained items, but none were usable."
            )

        return entries

    raise FeedParseError(
        f"Unsupported feed root element: {root.tag!r}."
    )


def dedupe_key(entry: dict[str, Any]) -> str:
    """
    Build a snapshot-global deterministic deduplication key.

    Identity falls back GUID -> URL -> title, matching the identity
    contract enforced by scripts/validate.py for RSS snapshots. The
    first feed (in configuration order) that carried a story wins, so
    category-specific feeds should be configured before broader ones.
    """
    entry_identity = (
        str(entry.get("guid") or "").strip()
        or str(entry.get("url") or "").strip()
        or str(entry.get("title") or "").strip()
    )

    return entry_identity


def collect() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Collect entries from all configured feeds."""

    config = load_config()
    feeds = config.get("feeds", [])
    collection_config = config.get("collection", {})

    if not isinstance(collection_config, dict):
        raise ValueError("RSS configuration field 'collection' must be an object.")

    raw_max_entries = collection_config.get("max_entries_per_feed", 50)
    raw_delay = collection_config.get("rate_limit_delay_seconds", 2)

    try:
        max_entries = int(raw_max_entries)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "collection.max_entries_per_feed must be an integer."
        ) from exc

    if max_entries < 0:
        raise ValueError(
            "collection.max_entries_per_feed cannot be negative."
        )

    try:
        delay = float(raw_delay)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "collection.rate_limit_delay_seconds must be numeric."
        ) from exc

    if delay < 0:
        raise ValueError(
            "collection.rate_limit_delay_seconds cannot be negative."
        )

    all_entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    if not feeds:
        print("No RSS/Atom feeds configured.")

    for index, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            failures.append(
                {
                    "feed": f"feed-{index + 1}",
                    "error": "Feed configuration entry is not an object",
                }
            )
            continue

        name = str(feed.get("name") or "Unknown")
        url = str(feed.get("url") or "").strip()
        source = str(feed.get("source") or "Unknown")

        if not url:
            failures.append(
                {
                    "feed": name,
                    "error": "No URL configured",
                }
            )
            continue

        if not is_valid_url(url):
            failures.append(
                {
                    "feed": name,
                    "error": "Invalid URL; only HTTP/HTTPS URLs are allowed",
                }
            )
            continue

        print(f"Fetching {name} ({source})...")

        content = fetch_feed(url)
        if content is None:
            failures.append(
                {
                    "feed": name,
                    "error": "Fetch failed after retries",
                }
            )
            continue

        try:
            entries = parse_feed(content, feed)
        except FeedParseError as exc:
            failures.append(
                {
                    "feed": name,
                    "error": str(exc),
                }
            )
            continue

        if not entries:
            print("    Feed is healthy but currently has 0 entries.")
        else:
            added = 0

            if max_entries > 0:
                for entry in entries:
                    key = dedupe_key(entry)

                    if key in seen_keys:
                        continue

                    seen_keys.add(key)
                    all_entries.append(entry)
                    added += 1

                    if added >= max_entries:
                        break

            print(
                f"    Parsed {len(entries)} entries; "
                f"added {added} after deduplication/limit"
            )

        if delay > 0 and index < len(feeds) - 1:
            time.sleep(delay)

    # Deterministic ordering:
    # publication date descending, then URL, then title.
    all_entries.sort(
        key=lambda e: (
            e.get("published_at") or "",
            e.get("url") or "",
            e.get("title") or "",
        ),
        reverse=True,
    )

    return all_entries, failures


def records_fingerprint(entries: list[dict[str, Any]]) -> str:
    """Create a deterministic fingerprint for entry records."""
    return json.dumps(
        entries,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def metadata_fingerprint(failures: list[dict[str, str]]) -> str:
    """Create a deterministic fingerprint for source failure metadata."""
    return json.dumps(
        failures,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def save_output(
    entries: list[dict[str, Any]],
    failures: list[dict[str, str]],
    snapshot_date: str,
) -> Path:
    """Save entries idempotently for the target reporting date."""

    if parse_ist_date(snapshot_date) is None:
        raise ValueError(
            f"Invalid snapshot date: {snapshot_date!r}. "
            "Expected YYYY-MM-DD."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"{snapshot_date}.json"

    new_records = records_fingerprint(entries)
    new_failures = metadata_fingerprint(failures)

    if output_path.exists():
        try:
            existing = json.loads(
                output_path.read_text(encoding="utf-8")
            )

            existing_entries = existing.get("entries", [])
            existing_meta = existing.get("meta", {})

            existing_failures = existing_meta.get("failures", [])

            if (
                records_fingerprint(existing_entries) == new_records
                and metadata_fingerprint(existing_failures) == new_failures
                and existing_meta.get("reportingDate") == snapshot_date
            ):
                print(
                    f"Entries and failure metadata unchanged for "
                    f"{snapshot_date}; keeping existing file."
                )
                return output_path

        except (json.JSONDecodeError, OSError, TypeError):
            pass

    output = {
        "meta": {
            "source": "RSS",
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "reportingDate": snapshot_date,
            "count": len(entries),
            "failures": failures,
        },
        "entries": entries,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        f.write("\n")

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect technology updates from RSS/Atom feeds."
    )
    parser.add_argument(
        "--date",
        type=str,
        help=(
            "Reporting date label (YYYY-MM-DD, IST edition). "
            "Default: current reporting date."
        ),
    )
    args = parser.parse_args()

    if args.date:
        parsed_date = parse_ist_date(args.date)

        if parsed_date is None:
            parser.error("--date must be in YYYY-MM-DD format.")

        snapshot_date = args.date
    else:
        snapshot_date = ist_today()

    print()
    print("TechPulse — RSS/Atom Collector")
    print("=" * 32)
    print(f"Reporting date: {snapshot_date} (IST edition)")
    print()

    try:
        entries, failures = collect()
        output_path = save_output(
            entries,
            failures,
            snapshot_date,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Collection finished.")
    print(f"Entries : {len(entries)}")

    if failures:
        print(f"Feed failures: {len(failures)}")
        for failure in failures:
            print(
                f"  - {failure['feed']}: "
                f"{failure['error']}"
            )

    print(f"Output  : {output_path}")
    print()

    # A completely empty but healthy RSS source is valid.
    # Fail only when every usable result is absent because at least
    # one feed actually failed.
    if not entries and failures:
        print(
            "ERROR: No entries collected and one or more feeds failed.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())