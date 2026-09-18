#!/usr/bin/env python3

"""
TechPulse — GitHub Collector

Collects repository metadata and releases for the configured tracked
repositories via the GitHub public REST API.

Authentication:
    Optional. Set the GITHUB_TOKEN (or GH_TOKEN) environment variable
    to raise the rate limit from 60 to 5,000 requests/hour.
    In GitHub Actions, map the workflow-provided token:

        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

    Local unauthenticated use remains fully supported.

Failure isolation:
    A single repository failure is recorded and does not abort the
    collection. Partial results are preserved and reported honestly.

Output:
    data/opensource/YYYY-MM-DD.json   (repository metadata)
    data/releases/YYYY-MM-DD.json     (releases)

Idempotency:
    Re-running for the same date with identical data does not rewrite
    the output files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request


GITHUB_API_BASE = "https://api.github.com"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "scripts" / "config" / "github.json"

REPO_META_DIR = PROJECT_ROOT / "data" / "opensource"
RELEASES_DIR = PROJECT_ROOT / "data" / "releases"

DEFAULT_TIMEOUT = 30
MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2
RATE_LIMIT_DELAY = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_snapshot_date() -> str:
    yesterday = (utc_now() - timedelta(days=1)).date()
    return yesterday.isoformat()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_token() -> str | None:
    """Return an optional GitHub token from the environment."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


class GitHubError(Exception):
    """Fatal GitHub API error for a single request."""


class RateLimited(GitHubError):
    """GitHub API rate limit exhausted."""


def api_get(url: str, token: str | None) -> dict[str, Any] | list[Any]:
    """Perform a GET request against the GitHub API."""

    headers = {
        "User-Agent": "TechPulse/1.0 (+https://github.com/singhtanishq/TechPulse)",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):

        if attempt > 0:
            wait = RETRY_BACKOFF_BASE ** attempt * 2
            print(f"    Retrying in {wait}s (attempt {attempt + 1}/{MAX_ATTEMPTS})...")
            time.sleep(wait)

        request = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                raw = response.read()

            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise GitHubError("GitHub API returned invalid JSON.") from exc

        except urllib.error.HTTPError as exc:
            if exc.code == 403 or exc.code == 429:
                # Distinguish rate limiting from other 403s via rate headers.
                remaining = exc.headers.get("x-ratelimit-remaining") if exc.headers else None
                if remaining == "0":
                    raise RateLimited(
                        "GitHub API rate limit exhausted "
                        "(set GITHUB_TOKEN to raise limits)."
                    ) from exc
                print(f"    GitHub HTTP {exc.code}.")
                last_error = GitHubError(f"GitHub API returned HTTP {exc.code}")
                continue
            if 500 <= exc.code < 600:
                print(f"    GitHub server error ({exc.code}).")
                last_error = GitHubError(f"GitHub API returned HTTP {exc.code}")
                continue
            if exc.code == 404:
                raise GitHubError("Repository not found (HTTP 404).") from exc
            raise GitHubError(f"GitHub API returned HTTP {exc.code}: {exc.reason}") from exc

        except urllib.error.URLError as exc:
            print(f"    Network error: {exc.reason}")
            last_error = GitHubError(f"Unable to reach GitHub API: {exc.reason}")
            continue

        except GitHubError:
            raise

        except Exception as exc:
            print(f"    Unexpected error: {exc}")
            last_error = GitHubError(f"Unexpected GitHub error: {exc}")
            continue

    raise GitHubError(f"Request failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error


def normalize_repo(repo_data: dict[str, Any], category: str) -> dict[str, Any]:
    """Normalize repository metadata."""
    return {
        "name": repo_data.get("name"),
        "full_name": repo_data.get("full_name"),
        "owner": (repo_data.get("owner") or {}).get("login"),
        "url": repo_data.get("html_url"),
        "description": repo_data.get("description"),
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "open_issues": repo_data.get("open_issues_count"),
        "language": repo_data.get("language"),
        "category": category,
        "default_branch": repo_data.get("default_branch"),
        "created_at": repo_data.get("created_at"),
        "updated_at": repo_data.get("updated_at"),
        "pushed_at": repo_data.get("pushed_at"),
        "archived": repo_data.get("archived", False),
        "source": "GitHub",
    }


def normalize_release(release_data: dict[str, Any], repo_full_name: str) -> dict[str, Any] | None:
    """
    Normalize a release.

    Prereleases and drafts are excluded (documented decision):
    TechPulse tracks stable releases to keep the daily signal clean.
    """

    if release_data.get("draft"):
        return None
    if release_data.get("prerelease"):
        return None

    tag_name = release_data.get("tag_name") or ""
    published_at = release_data.get("published_at")

    if not tag_name or not published_at:
        return None

    return {
        "project": repo_full_name.split("/")[-1],
        "repository": repo_full_name,
        "version": tag_name,
        "name": release_data.get("name"),
        "published_at": published_at,
        "url": release_data.get("html_url"),
        "source": "GitHub",
    }


def collect_repos(
    config: dict[str, Any],
    token: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """
    Collect metadata and releases for all tracked repositories.

    Returns (repos, releases, failures) where failures is a list of
    {repository, error} dicts. Partial results are preserved.
    """

    repos_config = config.get("tracked_repositories", [])
    collection_config = config.get("collection", {})
    max_releases = collection_config.get("max_releases_per_repo", 5)
    delay = collection_config.get("rate_limit_delay_seconds", 1)

    all_repos: list[dict[str, Any]] = []
    all_releases: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_releases: set[str] = set()

    rate_limit_aborted = False

    for repo_config in repos_config:
        owner = repo_config.get("owner")
        repo = repo_config.get("repo")
        category = repo_config.get("category", "general")
        full_name = f"{owner}/{repo}"

        if not owner or not repo:
            failures.append({"repository": str(repo_config), "error": "Invalid config entry"})
            continue

        print(f"Fetching {full_name}...")

        if rate_limit_aborted:
            failures.append({
                "repository": full_name,
                "error": "Skipped: GitHub rate limit exhausted earlier in run",
            })
            continue

        try:
            # Repository metadata
            repo_data = api_get(f"{GITHUB_API_BASE}/repos/{full_name}", token)
            if isinstance(repo_data, dict):
                all_repos.append(normalize_repo(repo_data, category))

            time.sleep(delay)

            # Releases (most recent first from the API)
            releases_data = api_get(
                f"{GITHUB_API_BASE}/repos/{full_name}/releases?per_page={max_releases}",
                token,
            )
            if isinstance(releases_data, list):
                for rel in releases_data:
                    normalized = normalize_release(rel, full_name)
                    if normalized is None:
                        continue
                    key = f"{full_name}@{normalized['version']}"
                    if key not in seen_releases:
                        seen_releases.add(key)
                        all_releases.append(normalized)

        except RateLimited as exc:
            print(f"    {exc}")
            failures.append({"repository": full_name, "error": str(exc)})
            rate_limit_aborted = True
            continue
        except GitHubError as exc:
            print(f"    Failed: {exc}")
            failures.append({"repository": full_name, "error": str(exc)})
            continue

        time.sleep(delay)

    # Deterministic ordering.
    all_repos.sort(key=lambda r: r.get("full_name") or "")
    all_releases.sort(
        key=lambda r: (r.get("published_at") or "", r.get("repository") or ""),
        reverse=True,
    )

    return all_repos, all_releases, failures


def records_fingerprint(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def save_json_idempotent(
    directory: Path,
    snapshot_date: str,
    payload: dict[str, Any],
    records_key: str,
) -> Path:
    """Write a dated JSON file unless its records are unchanged."""

    directory.mkdir(parents=True, exist_ok=True)

    output_path = directory / f"{snapshot_date}.json"
    new_records = records_fingerprint(payload[records_key])

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if records_fingerprint(existing.get(records_key, [])) == new_records:
                print(f"  Records unchanged for {snapshot_date}; keeping existing file.")
                return output_path
        except (json.JSONDecodeError, OSError):
            pass

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")

    return output_path


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Collect GitHub repository metadata and releases."
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

    token = get_token()
    auth_state = "authenticated" if token else "unauthenticated (60 req/hour limit)"

    print()
    print("TechPulse — GitHub Collector")
    print("=" * 32)
    print(f"Snapshot date : {snapshot_date}")
    print(f"Auth          : {auth_state}")
    print()

    try:
        config = load_config()
        repos, releases, failures = collect_repos(config, token)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    collected_at = utc_now().isoformat()

    repo_payload = {
        "meta": {
            "source": "GitHub",
            "collectedAt": collected_at,
            "snapshotDate": snapshot_date,
            "count": len(repos),
            "failures": failures,
        },
        "repositories": repos,
    }

    release_payload = {
        "meta": {
            "source": "GitHub",
            "collectedAt": collected_at,
            "snapshotDate": snapshot_date,
            "count": len(releases),
            "failures": failures,
        },
        "releases": releases,
    }

    repo_path = save_json_idempotent(REPO_META_DIR, snapshot_date, repo_payload, "repositories")
    releases_path = save_json_idempotent(RELEASES_DIR, snapshot_date, release_payload, "releases")

    print()
    print("Collection finished.")
    print(f"Repositories : {len(repos)}")
    print(f"Releases     : {len(releases)}")
    if failures:
        print(f"Failures     : {len(failures)}")
        for failure in failures:
            print(f"  - {failure['repository']}: {failure['error']}")
    print(f"Repos output    : {repo_path}")
    print(f"Releases output : {releases_path}")
    print()

    # Exit non-zero only when nothing at all was collected.
    if not repos and not releases:
        print("ERROR: No GitHub data could be collected.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
