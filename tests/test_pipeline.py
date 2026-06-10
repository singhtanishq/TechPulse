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
        self.assertEqual(len(records), 2)  # 3 records, 1 duplicate

    def test_prefers_english_description(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0001")
        self.assertIn("critical injection flaw", target["description"])

    def test_empty_reference_urls_dropped(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0001")
        self.assertEqual(target["references"], ["https://example.com/advisory-1"])

    def test_always_exposes_references_field(self):
        records = self.normalize_all()
        target = next(r for r in records if r["id"] == "CVE-2026-0002")
        self.assertEqual(target["references"], [])

    def test_record_without_id_is_invalid(self):
        self.assertIsNone(nvd.normalize_cve({"cve": {}}))

    def test_deterministic_sort_by_id(self):
        collected = self.normalize_all()
        result = sorted(collected, key=lambda v: v["id"])
        self.assertEqual([r["id"] for r in result], ["CVE-2026-0001", "CVE-2026-0002"])

    def test_fingerprint_stable_across_rebuilds(self):
        a = self.normalize_all()
        b = self.normalize_all()
        self.assertEqual(nvd.records_fingerprint(a), nvd.records_fingerprint(b))


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
        target = next(r for r in records if r["cve_id"] == "CVE-2026-1001")
        self.assertIs(target["known_ransomware_use"], True)

    def test_ransomware_unknown_is_false(self):
        records = self.normalize_all()
        target = next(r for r in records if r["cve_id"] == "CVE-2026-1002")
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
        self.assertIsNone(cisa.normalize_kev({"vendorProject": "X"}))


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
        record = github.normalize_release(self.releases[0], "facebook/react")
        self.assertIsNotNone(record)
        self.assertEqual(record["version"], "v19.2.0")

    def test_prerelease_excluded(self):
        self.assertIsNone(github.normalize_release(self.releases[1], "facebook/react"))

    def test_draft_excluded(self):
        self.assertIsNone(github.normalize_release(self.releases[2], "facebook/react"))

    def test_release_without_tag_excluded(self):
        self.assertIsNone(github.normalize_release(self.releases[3], "facebook/react"))

    def test_release_fields(self):
        record = github.normalize_release(self.releases[0], "facebook/react")
        self.assertEqual(record["project"], "react")
        self.assertEqual(record["repository"], "facebook/react")
        self.assertEqual(record["published_at"], "2026-09-17T15:00:00Z")


# ---------------------------------------------------------------- #
# RSS / Atom
# ---------------------------------------------------------------- #

class RSSTests(unittest.TestCase):

    def feed(self, name):
        return {"name": name, "url": f"https://example.com/{name}",
                "category": "tech", "source": name}

    def test_rss_parsing(self):
        entries = rss.parse_feed(load_text("rss_sample.xml").encode(), self.feed("Example"))
        self.assertEqual(len(entries), 4)

    def test_html_stripped_from_summary(self):
        entries = rss.parse_feed(load_text("rss_sample.xml").encode(), self.feed("Example"))
        first = entries[0]
        self.assertNotIn("<", first["summary"])
        self.assertIn("HTML", first["summary"])

    def test_entities_decoded_in_title(self):
        entries = rss.parse_feed(load_text("rss_sample.xml").encode(), self.feed("Example"))
        self.assertIn("&", entries[0]["title"])

    def test_missing_date_is_none(self):
        entries = rss.parse_feed(load_text("rss_sample.xml").encode(), self.feed("Example"))
        second = next(e for e in entries if e["title"] == "Story with missing date")
        self.assertIsNone(second["published_at"])

    def test_dangerous_link_url_dropped(self):
        entries = rss.parse_feed(load_text("rss_sample.xml").encode(), self.feed("Example"))
        js_entry = next(e for e in entries if e["guid"] == "guid-js-story")
        self.assertEqual(js_entry["url"], "")

    def test_summary_truncated_for_copyright_safety(self):
        long_summary = "x" * 2000
        entry = rss.normalize_entry("T", "https://example.com/a", long_summary,
                                    datetime(2026, 9, 17, tzinfo=timezone.utc), "g", self.feed("F"))
        self.assertLessEqual(len(entry["summary"]), 301)

    def test_atom_parsing(self):
        entries = rss.parse_feed(load_text("atom_sample.xml").encode(), self.feed("AtomExample"))
        # Third entry has no title/link and must be dropped.
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["url"], "https://example.org/post-1")

    def test_atom_uses_published_or_updated(self):
        entries = rss.parse_feed(load_text("atom_sample.xml").encode(), self.feed("AtomExample"))
        self.assertEqual(entries[1]["published_at"], "2026-09-16T08:30:00+00:00")

    def test_malformed_xml_returns_empty(self):
        entries = rss.parse_feed(b"<rss><channel><item>", self.feed("Broken"))
        self.assertEqual(entries, [])

    def test_rfc822_timezone_parsing(self):
        parsed = rss.parse_datetime("Wed, 16 Sep 2026 10:00:00 +0200")
        self.assertEqual(parsed.hour, 8)  # converted to UTC
        self.assertEqual(parsed.utcoffset(), timezone.utc.utcoffset(parsed))

    def test_legacy_zone_name_parsing(self):
        parsed = rss.parse_datetime("Wed, 16 Sep 2026 10:00:00 EDT")
        self.assertEqual(parsed.hour, 14)  # EDT = UTC-4


# ---------------------------------------------------------------- #
# Shared utilities
# ---------------------------------------------------------------- #

class UtilsTests(unittest.TestCase):

    def test_parse_iso_z(self):
        parsed = utils.parse_iso_datetime("2026-09-17T12:00:00Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.year, 2026)

    def test_parse_iso_invalid(self):
        self.assertIsNone(utils.parse_iso_datetime("not-a-date"))
        self.assertIsNone(utils.parse_iso_datetime(None))
        self.assertIsNone(utils.parse_iso_datetime(""))

    def test_format_relative_today_yesterday(self):
        now = datetime(2026, 9, 18, tzinfo=timezone.utc)
        self.assertEqual(utils.format_relative_date("2026-09-18T00:00:00Z", now), "Today")
        self.assertEqual(utils.format_relative_date("2026-09-17T00:00:00Z", now), "Yesterday")
        self.assertEqual(utils.format_relative_date("2026-09-11T00:00:00Z", now), "7 days ago")

    def test_status_model(self):
        self.assertEqual(utils.status_from_counts(0, 0, 0), "empty")
        self.assertEqual(utils.status_from_counts(0, 0, 2), "failed")
        self.assertEqual(utils.status_from_counts(100, 0, 0), "partial")
        self.assertEqual(utils.status_from_counts(100, 5, 0), "success")

    def test_latest_dated_file_prefers_newest_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "2026-09-16.json").write_text("{}", encoding="utf-8")
            (directory / "2026-09-17.json").write_text("{}", encoding="utf-8")
            (directory / "2026-09-15.json").write_text("{}", encoding="utf-8")
            latest = utils.latest_dated_file(directory)
            self.assertEqual(latest.name, "2026-09-17.json")

    def test_deduplicate_by_key(self):
        items = [{"id": "a", "v": 1}, {"id": "a", "v": 2}, {"id": "b", "v": 3}]
        result = utils.deduplicate_by_key(items, "id")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["v"], 1)

    def test_previous_utc_day(self):
        ref = datetime(2026, 9, 18, 5, 0, tzinfo=timezone.utc)
        previous = utils.previous_utc_day(ref)
        self.assertEqual(previous.date().isoformat(), "2026-09-17")
        self.assertEqual(previous.hour, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
