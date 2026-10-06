"""
TechPulse — Offline Unit Tests

Dependency-free unittest suite. All tests use fixtures and do NOT
hit live APIs.

Run:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from helpers import load_module, load_processors_utils  # noqa: E402

FIXTURES = TESTS_DIR / "fixtures"


def load_fixture(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- #
# Modules under test
# ---------------------------------------------------------------- #

nvd = load_module("techpulse_nvd_collect", "sources/nvd/collect.py")
cisa = load_module("techpulse_cisa_collect", "sources/cisa/collect.py")
github = load_module("techpulse_github_collect", "sources/github/collect.py")
rss = load_module("techpulse_rss_collect", "sources/rss/collect.py")
utils = load_processors_utils()

# Original ist_today, preserved for monkeypatch restoration.
IST_TODAY_ORIGINAL = utils.ist_today


# ---------------------------------------------------------------- #
# NVD
# ---------------------------------------------------------------- #

class NVDNormalizationTests(unittest.TestCase):

    def setUp(self):
        self.page = load_fixture("nvd_page.json")

    def normalize_all(self):
        records = []
        seen = set()

        for item in self.page["vulnerabilities"]:
            record = nvd.normalize_cve(item)

            if record is None:
                continue

            if record["id"] not in seen:
                seen.add(record["id"])
                records.append(record)

        return records

    def test_extracts_cvss_v31_primary(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0001")

        self.assertEqual(target["cvss"]["version"], "3.1")
        self.assertEqual(target["cvss"]["score"], 9.8)
        self.assertEqual(target["cvss"]["severity"], "CRITICAL")
        self.assertEqual(target["severity"], "CRITICAL")

    def test_missing_cvss_is_none_not_zero(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0002")

        self.assertIsNone(target["cvss"])
        self.assertIsNone(target["severity"])

    def test_duplicate_cve_id_dropped(self):
        records = self.normalize_all()
        ids = [r["id"] for r in records]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(records), 2)

    def test_prefers_english_description(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0001")

        self.assertIn("critical injection flaw", target["description"])

    def test_empty_reference_urls_dropped(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0001")

        self.assertEqual(
            target["references"],
            ["https://example.com/advisory-1"],
        )

    def test_always_exposes_references_field(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0002")

        self.assertEqual(target["references"], [])

    def test_record_without_id_is_invalid(self):
        self.assertIsNone(nvd.normalize_cve({"cve": {}}))

    def test_deterministic_sort_by_id(self):
        collected = self.normalize_all()
        result = sorted(collected, key=lambda v: v["id"])

        self.assertEqual(
            [r["id"] for r in result],
            ["CVE-2026-0001", "CVE-2026-0002"],
        )

    def test_fingerprint_stable_across_rebuilds(self):
        a = self.normalize_all()
        b = self.normalize_all()

        self.assertEqual(
            nvd.records_fingerprint(a),
            nvd.records_fingerprint(b),
        )


# ---------------------------------------------------------------- #
# CISA KEV
# ---------------------------------------------------------------- #

class CISANormalizationTests(unittest.TestCase):

    def setUp(self):
        self.catalog = load_fixture("cisa_kev.json")

    def normalize_all(self):
        records = []
        seen = set()

        for entry in self.catalog["vulnerabilities"]:
            record = cisa.normalize_kev(entry)

            if record is None:
                continue

            if record["cve_id"] not in seen:
                seen.add(record["cve_id"])
                records.append(record)

        return records

    def test_ransomware_known_is_boolean(self):
        records = self.normalize_all()
        target = next(
            r for r in records
            if r["cve_id"] == "CVE-2026-1001"
        )

        self.assertIs(target["known_ransomware_use"], True)

    def test_ransomware_unknown_is_false(self):
        records = self.normalize_all()
        target = next(
            r for r in records
            if r["cve_id"] == "CVE-2026-1002"
        )

        self.assertIs(target["known_ransomware_use"], False)

    def test_duplicate_kev_dropped(self):
        records = self.normalize_all()
        ids = [r["cve_id"] for r in records]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(records), 2)

    def test_cve_url_constructed(self):
        records = self.normalize_all()
        target = records[0]

        self.assertEqual(
            target["cve_url"],
            f"https://nvd.nist.gov/vuln/detail/{target['cve_id']}",
        )

    def test_entry_without_cve_id_invalid(self):
        self.assertIsNone(
            cisa.normalize_kev({"vendorProject": "X"})
        )


# ---------------------------------------------------------------- #
# GitHub
# ---------------------------------------------------------------- #

class GitHubNormalizationTests(unittest.TestCase):

    def setUp(self):
        self.repo = load_fixture("github_repo.json")[0]
        self.releases = load_fixture("github_releases.json")

    def test_repo_normalization(self):
        record = github.normalize_repo(self.repo, "frontend")

        self.assertEqual(record["full_name"], "facebook/react")
        self.assertEqual(record["owner"], "facebook")
        self.assertEqual(record["stars"], 250000)
        self.assertEqual(record["category"], "frontend")
        self.assertEqual(record["source"], "GitHub")

    def test_stable_release_included(self):
        record = github.normalize_release(
            self.releases[0],
            "facebook/react",
        )

        self.assertIsNotNone(record)
        self.assertEqual(record["version"], "v19.2.0")

    def test_prerelease_excluded(self):
        self.assertIsNone(
            github.normalize_release(
                self.releases[1],
                "facebook/react",
            )
        )

    def test_draft_excluded(self):
        self.assertIsNone(
            github.normalize_release(
                self.releases[2],
                "facebook/react",
            )
        )

    def test_release_without_tag_excluded(self):
        self.assertIsNone(
            github.normalize_release(
                self.releases[3],
                "facebook/react",
            )
        )

    def test_release_fields(self):
        record = github.normalize_release(
            self.releases[0],
            "facebook/react",
        )

        self.assertEqual(record["project"], "react")
        self.assertEqual(record["repository"], "facebook/react")
        self.assertEqual(
            record["published_at"],
            "2026-09-17T15:00:00Z",
        )


# ---------------------------------------------------------------- #
# RSS / Atom
# ---------------------------------------------------------------- #

class RSSTests(unittest.TestCase):

    def feed(self, name):
        return {
            "name": name,
            "url": f"https://example.com/{name}",
            "category": "tech",
            "source": name,
        }

    def test_rss_parsing(self):
        entries = rss.parse_feed(
            load_text("rss_sample.xml").encode(),
            self.feed("Example"),
        )

        self.assertEqual(len(entries), 4)

    def test_html_stripped_from_summary(self):
        entries = rss.parse_feed(
            load_text("rss_sample.xml").encode(),
            self.feed("Example"),
        )
        first = entries[0]

        self.assertNotIn("<", first["summary"])
        self.assertIn("HTML", first["summary"])

    def test_entities_decoded_in_title(self):
        entries = rss.parse_feed(
            load_text("rss_sample.xml").encode(),
            self.feed("Example"),
        )

        self.assertIn("&", entries[0]["title"])

    def test_missing_date_is_none(self):
        entries = rss.parse_feed(
            load_text("rss_sample.xml").encode(),
            self.feed("Example"),
        )
        second = next(
            e for e in entries
            if e["title"] == "Story with missing date"
        )

        self.assertIsNone(second["published_at"])

    def test_dangerous_link_url_dropped(self):
        entries = rss.parse_feed(
            load_text("rss_sample.xml").encode(),
            self.feed("Example"),
        )
        js_entry = next(
            e for e in entries
            if e["guid"] == "guid-js-story"
        )

        self.assertEqual(js_entry["url"], "")

    def test_summary_truncated_for_copyright_safety(self):
        long_summary = "x" * 2000

        entry = rss.normalize_entry(
            "T",
            "https://example.com/a",
            long_summary,
            datetime(
                2026,
                9,
                17,
                tzinfo=timezone.utc,
            ),
            "g",
            self.feed("F"),
        )

        self.assertIsNotNone(entry)
        self.assertLessEqual(len(entry["summary"]), 301)

    def test_atom_parsing(self):
        entries = rss.parse_feed(
            load_text("atom_sample.xml").encode(),
            self.feed("AtomExample"),
        )

        # Third entry has no title/link and must be dropped.
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0]["url"],
            "https://example.org/post-1",
        )

    def test_atom_uses_published_or_updated(self):
        entries = rss.parse_feed(
            load_text("atom_sample.xml").encode(),
            self.feed("AtomExample"),
        )

        self.assertEqual(
            entries[1]["published_at"],
            "2026-09-16T08:30:00+00:00",
        )

    def test_malformed_xml_raises_parse_error(self):
        with self.assertRaises(rss.FeedParseError):
            rss.parse_feed(
                b"<rss><channel><item>",
                self.feed("Broken"),
            )

    def test_healthy_empty_rss_feed_returns_empty(self):
        content = b"""
            <rss version="2.0">
                <channel>
                    <title>Empty Feed</title>
                    <link>https://example.com/</link>
                    <description>No current stories</description>
                </channel>
            </rss>
        """

        entries = rss.parse_feed(
            content,
            self.feed("Empty"),
        )

        self.assertEqual(entries, [])

    def test_healthy_empty_atom_feed_returns_empty(self):
        content = b"""
            <feed xmlns="http://www.w3.org/2005/Atom">
                <title>Empty Atom Feed</title>
                <id>https://example.com/</id>
            </feed>
        """

        entries = rss.parse_feed(
            content,
            self.feed("EmptyAtom"),
        )

        self.assertEqual(entries, [])

    def test_feed_with_only_unusable_items_raises_parse_error(self):
        content = b"""
            <rss version="2.0">
                <channel>
                    <title>Broken Content</title>
                    <item>
                        <description>Only content, no usable identity</description>
                    </item>
                </channel>
            </rss>
        """

        with self.assertRaises(rss.FeedParseError):
            rss.parse_feed(
                content,
                self.feed("BrokenContent"),
            )

    def test_rfc822_timezone_parsing(self):
        parsed = rss.parse_datetime(
            "Wed, 16 Sep 2026 10:00:00 +0200"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 8)
        self.assertEqual(
            parsed.utcoffset(),
            timezone.utc.utcoffset(parsed),
        )

    def test_legacy_zone_name_parsing(self):
        parsed = rss.parse_datetime(
            "Wed, 16 Sep 2026 10:00:00 EDT"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 14)

    def test_iso8601_offset_parsing(self):
        parsed = rss.parse_datetime(
            "2026-09-16T10:00:00+02:00"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 8)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_invalid_datetime_returns_none(self):
        self.assertIsNone(
            rss.parse_datetime("not-a-real-date")
        )
        self.assertIsNone(
            rss.parse_datetime("")
        )
        self.assertIsNone(
            rss.parse_datetime(None)
        )

    def test_invalid_feed_url_rejected(self):
        self.assertFalse(
            rss.is_valid_url("javascript:alert(1)")
        )
        self.assertFalse(
            rss.is_valid_url("file:///tmp/feed.xml")
        )
        self.assertFalse(
            rss.is_valid_url("not-a-url")
        )
        self.assertTrue(
            rss.is_valid_url("https://example.com/feed.xml")
        )

    def test_deduplication_is_global_by_entry_identity(self):
        # The same story syndicated by two different feeds (as real
        # publishers do across general + topic feeds) must collide on
        # one identity so it appears once per snapshot.
        first = rss.normalize_entry(
            "Same Story",
            "https://example.com/one",
            "",
            None,
            "same-guid",
            self.feed("FeedA"),
        )
        second = rss.normalize_entry(
            "Same Story",
            "https://example.com/one",
            "",
            None,
            "same-guid",
            self.feed("FeedB"),
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

        self.assertEqual(
            rss.dedupe_key(first),
            rss.dedupe_key(second),
        )

    def test_deduplication_falls_back_to_url_then_title(self):
        # No GUID: the URL carries identity.
        by_url_a = rss.normalize_entry(
            "Story A",
            "https://example.com/story",
            "",
            None,
            "",
            self.feed("FeedA"),
        )
        by_url_b = rss.normalize_entry(
            "Story A retitled",
            "https://example.com/story",
            "",
            None,
            "",
            self.feed("FeedB"),
        )
        self.assertEqual(
            rss.dedupe_key(by_url_a),
            rss.dedupe_key(by_url_b),
        )

        # No GUID and no URL: the title carries identity.
        by_title_a = rss.normalize_entry(
            "Shared Headline",
            "",
            "",
            None,
            "",
            self.feed("FeedA"),
        )
        by_title_b = rss.normalize_entry(
            "Shared Headline",
            "",
            "",
            None,
            "",
            self.feed("FeedB"),
        )
        self.assertEqual(
            rss.dedupe_key(by_title_a),
            rss.dedupe_key(by_title_b),
        )

    def test_distinct_stories_from_different_feeds_do_not_collide(self):
        first = rss.normalize_entry(
            "Story One",
            "https://example.com/one",
            "",
            None,
            "guid-one",
            self.feed("FeedA"),
        )
        second = rss.normalize_entry(
            "Story Two",
            "https://example.com/two",
            "",
            None,
            "guid-two",
            self.feed("FeedB"),
        )

        self.assertNotEqual(
            rss.dedupe_key(first),
            rss.dedupe_key(second),
        )


class RSSCollectionTests(unittest.TestCase):

    def test_healthy_empty_feed_is_not_recorded_as_failure(self):
        config = {
            "feeds": [
                {
                    "name": "Empty",
                    "url": "https://example.com/empty.xml",
                    "category": "tech",
                    "source": "Example",
                }
            ],
            "collection": {
                "max_entries_per_feed": 50,
                "rate_limit_delay_seconds": 0,
            },
        }

        with (
            mock.patch.object(
                rss,
                "load_config",
                return_value=config,
            ),
            mock.patch.object(
                rss,
                "fetch_feed",
                return_value=b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>",
            ),
        ):
            entries, failures = rss.collect()

        self.assertEqual(entries, [])
        self.assertEqual(failures, [])

    def test_failed_feed_is_recorded(self):
        config = {
            "feeds": [
                {
                    "name": "Broken",
                    "url": "https://example.com/broken.xml",
                    "category": "tech",
                    "source": "Example",
                }
            ],
            "collection": {
                "max_entries_per_feed": 50,
                "rate_limit_delay_seconds": 0,
            },
        }

        with (
            mock.patch.object(
                rss,
                "load_config",
                return_value=config,
            ),
            mock.patch.object(
                rss,
                "fetch_feed",
                return_value=None,
            ),
        ):
            entries, failures = rss.collect()

        self.assertEqual(entries, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["feed"], "Broken")

    def test_malformed_feed_is_recorded_as_failure(self):
        config = {
            "feeds": [
                {
                    "name": "Broken XML",
                    "url": "https://example.com/broken.xml",
                    "category": "tech",
                    "source": "Example",
                }
            ],
            "collection": {
                "max_entries_per_feed": 50,
                "rate_limit_delay_seconds": 0,
            },
        }

        with (
            mock.patch.object(
                rss,
                "load_config",
                return_value=config,
            ),
            mock.patch.object(
                rss,
                "fetch_feed",
                return_value=b"<rss><channel><item>",
            ),
        ):
            entries, failures = rss.collect()

        self.assertEqual(entries, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["feed"], "Broken XML")
        self.assertIn("Malformed XML", failures[0]["error"])

    def test_empty_feed_does_not_abort_other_feeds(self):
        config = {
            "feeds": [
                {
                    "name": "Empty",
                    "url": "https://example.com/empty.xml",
                    "category": "tech",
                    "source": "Example",
                },
                {
                    "name": "Working",
                    "url": "https://example.com/working.xml",
                    "category": "tech",
                    "source": "Example",
                },
            ],
            "collection": {
                "max_entries_per_feed": 50,
                "rate_limit_delay_seconds": 0,
            },
        }

        working_content = b"""
            <rss version="2.0">
                <channel>
                    <title>Working Feed</title>
                    <item>
                        <title>Working Story</title>
                        <link>https://example.com/story</link>
                        <guid>working-1</guid>
                    </item>
                </channel>
            </rss>
        """

        fetch_results = [
            b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>",
            working_content,
        ]

        def fake_fetch(_url):
            return fetch_results.pop(0)

        with (
            mock.patch.object(
                rss,
                "load_config",
                return_value=config,
            ),
            mock.patch.object(
                rss,
                "fetch_feed",
                side_effect=fake_fetch,
            ),
        ):
            entries, failures = rss.collect()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Working Story")
        self.assertEqual(failures, [])

    def test_zero_max_entries_collects_no_entries(self):
        config = {
            "feeds": [
                {
                    "name": "Example",
                    "url": "https://example.com/feed.xml",
                    "category": "tech",
                    "source": "Example",
                }
            ],
            "collection": {
                "max_entries_per_feed": 0,
                "rate_limit_delay_seconds": 0,
            },
        }

        content = b"""
            <rss version="2.0">
                <channel>
                    <title>Example Feed</title>
                    <item>
                        <title>Story</title>
                        <link>https://example.com/story</link>
                        <guid>story-1</guid>
                    </item>
                </channel>
            </rss>
        """

        with (
            mock.patch.object(
                rss,
                "load_config",
                return_value=config,
            ),
            mock.patch.object(
                rss,
                "fetch_feed",
                return_value=content,
            ),
        ):
            entries, failures = rss.collect()

        self.assertEqual(entries, [])
        self.assertEqual(failures, [])

    def test_invalid_configured_url_is_failure(self):
        config = {
            "feeds": [
                {
                    "name": "Invalid",
                    "url": "javascript:alert(1)",
                    "category": "tech",
                    "source": "Example",
                }
            ],
            "collection": {
                "max_entries_per_feed": 50,
                "rate_limit_delay_seconds": 0,
            },
        }

        with mock.patch.object(
            rss,
            "load_config",
            return_value=config,
        ):
            entries, failures = rss.collect()

        self.assertEqual(entries, [])
        self.assertEqual(len(failures), 1)
        self.assertIn(
            "Invalid URL",
            failures[0]["error"],
        )


class RSSOutputTests(unittest.TestCase):

    def test_save_output_preserves_idempotency_when_records_and_failures_match(self):
        entries = [
            {
                "title": "Story",
                "url": "https://example.com/story",
                "summary": "",
                "published_at": None,
                "guid": "story-1",
                "feed_url": "https://example.com/feed",
                "feed_name": "Example",
                "feed_category": "tech",
                "feed_source": "Example",
                "source": "RSS",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            with mock.patch.object(
                rss,
                "OUTPUT_DIR",
                output_dir,
            ):
                path = rss.save_output(
                    entries,
                    [],
                    "2026-09-28",
                )

                first_content = path.read_text(
                    encoding="utf-8"
                )

                path_again = rss.save_output(
                    entries,
                    [],
                    "2026-09-28",
                )

                second_content = path_again.read_text(
                    encoding="utf-8"
                )

            self.assertEqual(path, path_again)
            self.assertEqual(first_content, second_content)

    def test_save_output_updates_failure_metadata_when_records_match(self):
        entries = [
            {
                "title": "Story",
                "url": "https://example.com/story",
                "summary": "",
                "published_at": None,
                "guid": "story-1",
                "feed_url": "https://example.com/feed",
                "feed_name": "Example",
                "feed_category": "tech",
                "feed_source": "Example",
                "source": "RSS",
            }
        ]

        initial_failures = [
            {
                "feed": "BrokenFeed",
                "error": "Fetch failed after retries",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            with mock.patch.object(
                rss,
                "OUTPUT_DIR",
                output_dir,
            ):
                path = rss.save_output(
                    entries,
                    initial_failures,
                    "2026-09-28",
                )

                updated_failures: list[dict[str, str]] = []

                rss.save_output(
                    entries,
                    updated_failures,
                    "2026-09-28",
                )

            payload = json.loads(
                path.read_text(encoding="utf-8")
            )

            self.assertEqual(
                payload["meta"]["failures"],
                [],
            )


# ---------------------------------------------------------------- #
# Shared utilities
# ---------------------------------------------------------------- #

class UtilsTests(unittest.TestCase):

    def test_parse_iso_z(self):
        parsed = utils.parse_iso_datetime(
            "2026-09-17T12:00:00Z"
        )

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.year, 2026)

    def test_parse_iso_invalid(self):
        self.assertIsNone(
            utils.parse_iso_datetime("not-a-date")
        )
        self.assertIsNone(
            utils.parse_iso_datetime(None)
        )
        self.assertIsNone(
            utils.parse_iso_datetime("")
        )

    def test_status_model(self):
        self.assertEqual(
            utils.status_from_counts(0, 0, 0),
            "empty",
        )
        self.assertEqual(
            utils.status_from_counts(0, 0, 2),
            "failed",
        )
        self.assertEqual(
            utils.status_from_counts(100, 0, 0),
            "empty",
        )
        self.assertEqual(
            utils.status_from_counts(100, 5, 0),
            "success",
        )
        self.assertEqual(
            utils.status_from_counts(100, 5, 3),
            "partial",
        )
        self.assertEqual(
            utils.status_from_counts(100, 0, 3),
            "partial",
        )

    def test_latest_dated_file_prefers_newest_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            (directory / "2026-09-16.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (directory / "2026-09-17.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (directory / "2026-09-15.json").write_text(
                "{}",
                encoding="utf-8",
            )

            latest = utils.latest_dated_file(directory)

            self.assertIsNotNone(latest)
            self.assertEqual(
                latest.name,
                "2026-09-17.json",
            )

    def test_dated_file_for_requires_exact_reporting_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            (directory / "2026-09-16.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (directory / "2026-09-17.json").write_text(
                "{}",
                encoding="utf-8",
            )

            exact = utils.dated_file_for(
                directory,
                "2026-09-17",
            )
            missing = utils.dated_file_for(
                directory,
                "2026-09-18",
            )

            self.assertIsNotNone(exact)
            self.assertEqual(
                exact.name,
                "2026-09-17.json",
            )
            self.assertIsNone(missing)

    def test_dated_file_for_none_allows_latest_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            (directory / "2026-09-16.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (directory / "2026-09-17.json").write_text(
                "{}",
                encoding="utf-8",
            )

            latest = utils.dated_file_for(
                directory,
                None,
            )

            self.assertIsNotNone(latest)
            self.assertEqual(
                latest.name,
                "2026-09-17.json",
            )

    def test_deduplicate_by_key(self):
        items = [
            {"id": "a", "v": 1},
            {"id": "a", "v": 2},
            {"id": "b", "v": 3},
        ]

        result = utils.deduplicate_by_key(
            items,
            "id",
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["v"], 1)


class ISTReportingTests(unittest.TestCase):
    """Tests for the IST (Asia/Kolkata) reporting-date model.

    The edition for reporting date X covers the previous IST day:
    [X-1 00:00 IST, X 00:00 IST).
    IST is a fixed UTC+05:30 offset.
    """

    def test_ist_offset_is_fixed_five_thirty(self):
        self.assertEqual(
            utils.ist_now().utcoffset().total_seconds(),
            5.5 * 3600,
        )

    def test_ist_day_window_boundaries(self):
        # Edition 2026-09-28 covers IST day 2026-09-27,
        # i.e. UTC [2026-09-26 18:30, 2026-09-27 18:30).
        start, end = utils.ist_day_window("2026-09-28")

        self.assertEqual(
            start.isoformat(),
            "2026-09-26T18:30:00+00:00",
        )
        self.assertEqual(
            end.isoformat(),
            "2026-09-27T18:30:00+00:00",
        )

    def test_ist_day_window_year_boundary(self):
        # Edition 2026-01-01 covers IST day 2025-12-31.
        start, end = utils.ist_day_window("2026-01-01")

        self.assertEqual(
            start.isoformat(),
            "2025-12-30T18:30:00+00:00",
        )
        self.assertEqual(
            end.isoformat(),
            "2025-12-31T18:30:00+00:00",
        )

    def test_ist_date_of_instant(self):
        # 18:29:59 UTC = 23:59:59 IST — same IST day.
        self.assertEqual(
            utils.ist_date_of(
                datetime(
                    2026,
                    9,
                    26,
                    18,
                    29,
                    59,
                    tzinfo=timezone.utc,
                )
            ),
            "2026-09-26",
        )

        # 18:30:00 UTC = 00:00:00 IST next day.
        self.assertEqual(
            utils.ist_date_of(
                datetime(
                    2026,
                    9,
                    26,
                    18,
                    30,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            "2026-09-27",
        )

        # 23:00 UTC = 04:30 IST next day.
        self.assertEqual(
            utils.ist_date_of(
                datetime(
                    2026,
                    9,
                    26,
                    23,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            "2026-09-27",
        )

    def test_in_ist_day_with_date_only_value(self):
        # Date-only values must match as calendar dates, never be
        # reinterpreted as UTC instants.
        self.assertTrue(
            utils.in_ist_day(
                "2026-09-27",
                "2026-09-27",
            )
        )
        self.assertFalse(
            utils.in_ist_day(
                "2026-09-26",
                "2026-09-27",
            )
        )

    def test_in_ist_day_with_iso_timestamp(self):
        # 2026-09-26T20:00:00Z = 2026-09-27 01:30 IST.
        self.assertTrue(
            utils.in_ist_day(
                "2026-09-26T20:00:00Z",
                "2026-09-27",
            )
        )

        # 2026-09-26T17:00:00Z = 2026-09-26 22:30 IST.
        self.assertTrue(
            utils.in_ist_day(
                "2026-09-26T17:00:00Z",
                "2026-09-26",
            )
        )

        self.assertFalse(
            utils.in_ist_day(
                "2026-09-26T17:00:00Z",
                "2026-09-27",
            )
        )

    def test_in_ist_day_invalid_values(self):
        self.assertFalse(
            utils.in_ist_day(
                None,
                "2026-09-27",
            )
        )
        self.assertFalse(
            utils.in_ist_day(
                "",
                "2026-09-27",
            )
        )
        self.assertFalse(
            utils.in_ist_day(
                "garbage",
                "2026-09-27",
            )
        )

    def test_resolve_reporting_date_explicit_input(self):
        date, reason = utils.resolve_reporting_date(
            "schedule",
            "2026-09-15",
        )

        self.assertEqual(date, "2026-09-15")
        self.assertIsInstance(reason, str)

    def test_resolve_reporting_date_rejects_bad_format(self):
        with self.assertRaises(ValueError):
            utils.resolve_reporting_date(
                "schedule",
                "2026/09/15",
            )

    def test_resolve_reporting_date_never_skips_ahead(self):
        # With a future-dated newest snapshot (bad manual backfill),
        # the resolver must fall back to the current IST date, never
        # publish further into the future.
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily"
            daily.mkdir()

            (daily / "2027-01-01.json").write_text(
                "{}",
                encoding="utf-8",
            )

            original = utils.DAILY_DIR
            utils.DAILY_DIR = daily

            try:
                date, _ = utils.resolve_reporting_date(
                    "manual",
                    None,
                )
            finally:
                utils.DAILY_DIR = original

            self.assertEqual(
                date,
                utils.ist_today(),
            )

    def test_resolve_reporting_date_backfills_missed_day(self):
        # Newest snapshot is two days old (yesterday's run failed):
        # the resolver must backfill the missing day, not skip ahead.
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily"
            daily.mkdir()

            (daily / "2026-09-20.json").write_text(
                "{}",
                encoding="utf-8",
            )

            original_daily = utils.DAILY_DIR
            original_ist_today = utils.ist_today

            utils.DAILY_DIR = daily

            try:
                # Simulate current IST date as 2026-09-23.
                utils.ist_today = (
                    lambda offset_minutes=0: "2026-09-23"
                )

                date, _ = utils.resolve_reporting_date(
                    "schedule",
                    None,
                )
            finally:
                utils.DAILY_DIR = original_daily
                utils.ist_today = original_ist_today

            self.assertEqual(
                date,
                "2026-09-21",
            )

    def test_resolve_reporting_date_scheduled_uses_current_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily"
            daily.mkdir()

            (daily / "2026-09-26.json").write_text(
                "{}",
                encoding="utf-8",
            )

            original_daily = utils.DAILY_DIR
            original_ist_today = utils.ist_today

            utils.DAILY_DIR = daily

            try:
                utils.ist_today = (
                    lambda offset_minutes=0: "2026-09-27"
                )

                date, _ = utils.resolve_reporting_date(
                    "schedule",
                    None,
                )
            finally:
                utils.DAILY_DIR = original_daily
                utils.ist_today = original_ist_today

            self.assertEqual(
                date,
                "2026-09-27",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)