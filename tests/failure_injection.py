"""
TechPulse — Failure Injection Tests (offline)

Exercises failure paths of the real collector/processor code with
patched endpoints and inputs. No live API traffic.

Run:
    python3 tests/failure_injection.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import contextlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))

from helpers import load_module, load_processors_utils  # noqa: E402

nvd = load_module("fi_nvd_collect", "sources/nvd/collect.py")
github = load_module("fi_github_collect", "sources/github/collect.py")
rss = load_module("fi_rss_collect", "sources/rss/collect.py")

# Speed up retries for offline failure simulation.
nvd.REQUEST_DELAY_SECONDS = 0
github.RATE_LIMIT_DELAY = 0
rss.SUMMARY_MAX_CHARS = 300


class NVDFailureTests(unittest.TestCase):
    """NVD collector behavior when the API is unreachable."""

    def test_unreachable_endpoint_raises_after_retries(self):
        original_url = nvd.API_URL
        nvd.API_URL = "https://127.0.0.1:9/rest/json/cves/2.0"  # Nothing listens here.
        try:
            with self.assertRaises(RuntimeError) as ctx:
                nvd.fetch_page(0, 10, datetime.now(timezone.utc) - timedelta(days=1),
                               datetime.now(timezone.utc))
            self.assertIn("attempts", str(ctx.exception))
        finally:
            nvd.API_URL = original_url

    def test_invalid_json_raises(self):
        # Patch urlopen to return non-JSON bytes.
        class FakeResponse(io.BytesIO):
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            return FakeResponse(b"this is not json {")

        original = nvd.urllib.request.urlopen
        nvd.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(RuntimeError) as ctx:
                nvd.fetch_page(0, 10, datetime.now(timezone.utc), datetime.now(timezone.utc))
            self.assertIn("invalid JSON", str(ctx.exception))
        finally:
            nvd.urllib.request.urlopen = original

    def test_empty_result_collection(self):
        """totalResults=0 must produce an empty list, not an error."""

        def fake_fetch(start_index, results_per_page, start_date, end_date):
            return {"totalResults": 0, "vulnerabilities": []}

        original = nvd.fetch_page
        nvd.fetch_page = fake_fetch
        try:
            result = nvd.collect(datetime.now(timezone.utc) - timedelta(days=1),
                                 datetime.now(timezone.utc))
            self.assertEqual(result, [])
        finally:
            nvd.fetch_page = original


class GitHubFailureTests(unittest.TestCase):
    """GitHub collector failure isolation: one repo failing preserves others."""

    def _run_collect(self, api_get_impl):
        config = {
            "tracked_repositories": [
                {"owner": "good", "repo": "one", "category": "x"},
                {"owner": "bad", "repo": "two", "category": "x"},
                {"owner": "good", "repo": "three", "category": "x"},
            ],
            "collection": {"max_releases_per_repo": 5, "rate_limit_delay_seconds": 0},
        }

        def api_get(url, token):
            return api_get_impl(url, token)

        original_get = github.api_get
        github.api_get = api_get
        original_sleep = github.time.sleep
        github.time.sleep = lambda s: None
        try:
            return github.collect_repos(config, token=None)
        finally:
            github.api_get = original_get
            github.time.sleep = original_sleep

    def test_single_repo_404_preserves_others(self):
        fixture = json.loads((PROJECT_ROOT / "tests/fixtures/github_repo.json").read_text())

        def impl(url, token):
            if "/repos/bad/two" in url and "/releases" not in url:
                raise github.GitHubError("Repository not found (HTTP 404).")
            if url.endswith("/repos/good/one"):
                return fixture[0]
            if url.endswith("/repos/good/three"):
                repo = dict(fixture[0])
                repo["full_name"] = "good/three"
                repo["name"] = "three"
                return repo
            if "/releases" in url:
                return []
            return {}

        repos, releases, failures = self._run_collect(impl)
        self.assertEqual(len(repos), 2)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["repository"], "bad/two")
        self.assertIn("404", failures[0]["error"])

    def test_rate_limit_marks_remaining_repos_skipped(self):
        fixture = json.loads((PROJECT_ROOT / "tests/fixtures/github_repo.json").read_text())

        def impl(url, token):
            if url.endswith("/repos/good/one"):
                return fixture[0]
            if "/repos/good/one/releases" in url:
                return []
            if url.endswith("/repos/bad/two"):
                raise github.RateLimited("GitHub API rate limit exhausted")
            raise AssertionError("should not be called after rate limit")

        repos, releases, failures = self._run_collect(impl)
        self.assertEqual(len(repos), 1)
        # bad/two failed, good/three skipped.
        self.assertEqual(len(failures), 2)
        skipped = [f for f in failures if "Skipped" in f["error"]]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["repository"], "good/three")


class RSSFailureTests(unittest.TestCase):
    """RSS collector continues when individual feeds fail."""

    def test_failed_feed_isolated(self):
        feeds_config = {
            "feeds": [
                {"name": "Good", "url": "https://good.example/feed", "category": "tech", "source": "Good"},
                {"name": "Broken", "url": "https://broken.example/feed", "category": "tech", "source": "Broken"},
            ],
            "collection": {"max_entries_per_feed": 10, "rate_limit_delay_seconds": 0},
        }

        rss_entry = {
            "title": "Entry",
            "url": "https://good.example/a",
            "summary": "s",
            "published_at": "2026-09-17T10:00:00+00:00",
            "guid": "g1",
            "feed_url": "https://good.example/feed",
            "feed_name": "Good",
            "feed_category": "tech",
            "feed_source": "Good",
            "source": "RSS",
        }

        original_load = rss.load_config
        original_fetch = rss.fetch_feed
        original_parse = rss.parse_feed
        original_sleep = rss.time.sleep
        rss.load_config = lambda: feeds_config
        rss.fetch_feed = lambda url: None if "broken" in url else b"<ok/>"
        rss.parse_feed = lambda content, feed: [dict(rss_entry)] if "good" in feed["url"] else []
        rss.time.sleep = lambda s: None
        try:
            entries, failures = rss.collect()
        finally:
            rss.load_config = original_load
            rss.fetch_feed = original_fetch
            rss.parse_feed = original_parse
            rss.time.sleep = original_sleep

        self.assertEqual(len(entries), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["feed"], "Broken")


class ProcessorEmptyInputTests(unittest.TestCase):
    """Processors must survive missing/empty raw data without crashing."""

    def _load_processor(self, relpath, name):
        module = load_module(name, relpath)
        return module

    def test_security_with_no_data(self):
        security = self._load_processor("processors/security.py", "fi_security")
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            original_nvd = security.NVD_DIR
            original_cisa = security.CISA_DIR
            security.NVD_DIR = empty
            security.CISA_DIR = empty
            try:
                result = security.process_security(
                    datetime(2026, 9, 17, tzinfo=timezone.utc),
                    datetime(2026, 9, 18, tzinfo=timezone.utc) - timedelta(milliseconds=1),
                )
            finally:
                security.NVD_DIR = original_nvd
                security.CISA_DIR = original_cisa

        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["meta"]["sources"]["nvd"]["status"], "empty")
        self.assertEqual(result["meta"]["sources"]["cisa"]["status"], "empty")

    def test_releases_with_no_data(self):
        releases = self._load_processor("processors/releases.py", "fi_releases")
        with tempfile.TemporaryDirectory() as tmp:
            original = releases.RELEASES_DIR
            releases.RELEASES_DIR = Path(tmp)
            try:
                result = releases.process_releases(
                    datetime(2026, 9, 17, tzinfo=timezone.utc),
                    datetime(2026, 9, 18, tzinfo=timezone.utc) - timedelta(milliseconds=1),
                )
            finally:
                releases.RELEASES_DIR = original

        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["meta"]["sources"]["github"]["status"], "empty")

    def test_opensource_with_no_data(self):
        opensource = self._load_processor("processors/opensource.py", "fi_opensource")
        with tempfile.TemporaryDirectory() as tmp:
            original = opensource.REPO_META_DIR
            opensource.REPO_META_DIR = Path(tmp)
            try:
                result = opensource.process_opensource("2026-09-17")
            finally:
                opensource.REPO_META_DIR = original

        self.assertEqual(result["summary"]["totalTracked"], 0)
        self.assertEqual(result["meta"]["sources"]["github"]["status"], "empty")
        # Growth must be unavailable, never fabricated.
        self.assertEqual(result["summary"]["growthBasis"], "unavailable")

    def test_tech_with_no_data(self):
        tech = self._load_processor("processors/tech.py", "fi_tech")
        with tempfile.TemporaryDirectory() as tmp:
            original = tech.TECH_DIR
            tech.TECH_DIR = Path(tmp)
            try:
                result = tech.process_tech(
                    datetime(2026, 9, 17, tzinfo=timezone.utc),
                    datetime(2026, 9, 18, tzinfo=timezone.utc) - timedelta(milliseconds=1),
                )
            finally:
                tech.TECH_DIR = original

        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["meta"]["sources"]["rss"]["status"], "empty")

    def test_history_with_corrupt_and_valid_mix(self):
        history = self._load_processor("processors/history.py", "fi_history")
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            good = {
                "date": "2026-09-17",
                "generatedAt": "2026-09-18T02:00:00+00:00",
                "snapshot": {"cves": 5, "knownExploited": 0, "kevAdded": 0,
                             "releases": 1, "projects": 2, "techEntries": 3},
            }
            (daily / "2026-09-17.json").write_text(json.dumps(good), encoding="utf-8")
            (daily / "2026-09-16.json").write_text("{corrupt json", encoding="utf-8")
            (daily / "not-a-date.json").write_text("{}", encoding="utf-8")
            (daily / "2026-09-15.json").write_text(json.dumps({"no": "fields"}), encoding="utf-8")

            original = history.DAILY_DIR
            history.DAILY_DIR = daily
            try:
                result = history.process_history()
            finally:
                history.DAILY_DIR = original

        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["date"], "2026-09-17")
        # Three bad files must have produced warnings, not crashes.
        self.assertGreaterEqual(len(result["meta"]["warnings"]), 3)


class PipelineExitCodeTests(unittest.TestCase):
    """run_pipeline exit semantics (all-collectors-failed => exit 1)."""

    def test_invalid_date_rejected(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts/run_pipeline.py"), "--date", "not-a-date"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid date", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
