#!/usr/bin/env python3

"""
TechPulse — GitHub Collector

Collects repository metadata and releases from GitHub public API
for configured tracked repositories.
"""

from __future__ import annotations

import argparse
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
OUTPUT_DIR = PROJECT_ROOT / "data" / "releases"
REPO_META_DIR = PROJECT_ROOT / "data" / "opensource"

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RATE_LIMIT_DELAY = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
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


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_github_token() -> str | None:
    """Get GitHub token from environment if available."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def make_request(url: str, token: str | None = None) -> tuple[int, bytes]:
    """Make a GitHub API request with optional authentication."""
    headers = {
        "User-Agent": "TechPulse/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method="GET")

    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
        return response.status, response.read()


def fetch_with_retry(url: str, token: str | None = None) -> dict[str, Any] | list[Any] | None:
    """Fetch from GitHub API with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            status, raw = make_request(url, token)
            if status == 403:
                # Check rate limit
                print(f"GitHub API rate limited (403). Waiting before retry...")
                time.sleep(60 * (attempt + 1))
                continue
            if status == 404:
                return None
            if status == 429:
                wait_time = 60 * (attempt + 1)
                print(f"Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            if 500 <= status < 600:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                print(f"Server error ({status}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            if status != 200:
                raise RuntimeError(f"GitHub API returned HTTP {status}")
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print(f"GitHub API rate limited (403). Waiting before retry...")
                time.sleep(60 * (attempt + 1))
                last_exception = exc
                continue
            if exc.code == 404:
                return None
            if exc.code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            if 500 <= exc.code < 600:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                print(f"Server error ({exc.code}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                last_exception = exc
                continue
            raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {exc.reason}") from exc
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
            raise RuntimeError("GitHub API returned invalid JSON.") from exc

    if last_exception:
        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {last_exception}") from last_exception
    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")


def normalize_repo(repo_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize repository metadata."""
    return {
        "id": repo_data.get("id"),
        "name": repo_data.get("name"),
        "full_name": repo_data.get("full_name"),
        "owner": repo_data.get("owner", {}).get("login"),
        "url": repo_data.get("html_url"),
        "description": repo_data.get("description"),
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "watchers": repo_data.get("watchers_count"),
        "open_issues": repo_data.get("open_issues_count"),
        "language": repo_data.get("language"),
        "default_branch": repo_data.get("default_branch"),
        "created_at": repo_data.get("created_at"),
        "updated_at": repo_data.get("updated_at"),
        "pushed_at": repo_data.get("pushed_at"),
        "source": "GitHub",
        "collected_at": utc_now().isoformat(),
    }


def normalize_release(release_data: dict[str, Any], repo_full_name: str) -> dict[str, Any] | None:
    """Normalize release data."""
    if release_data.get("draft") or release_data.get("prerelease"):
        return None

    tag_name = release_data.get("tag_name", "")
    published_at = release_data.get("published_at")

    return {
        "project": repo_full_name.split("/")[-1],
        "repository": repo_full_name,
        "version": tag_name,
        "published_at": published_at,
        "url": release_data.get("html_url"),
        "source": "GitHub",
        "description": release_data.get("body"),
    }


def collect_repos(config: dict[str, Any], token: str | None) -> tuple[list[dict], list[dict]]:
    """Collect repository metadata and releases for all tracked repos."""
    repos_config = config.get("tracked_repositories", [])
    collection_config = config.get("collection", {})
    include_prereleases = collection_config.get("include_prereleases", False)
    max_releases = collection_config.get("max_releases_per_repo", 5)
    delay = collection_config.get("rate_limit_delay_seconds", 1)

    all_repos = []
    all_releases = []
    seen_releases: set[str] = set()

    for repo_config in repos_config:
        owner = repo_config["owner"]
        repo = repo_config["repo"]
        full_name = f"{owner}/{repo}"

        print(f"Fetching {full_name}...")

        # Fetch repo metadata
        repo_url = f"{GITHUB_API_BASE}/repos/{full_name}"
        repo_data = fetch_with_retry(repo_url, token)
        if repo_data:
            all_repos.append(normalize_repo(repo_data))

        # Fetch releases
        releases_url = f"{GITHUB_API_BASE}/repos/{full_name}/releases?per_page={max_releases}"
        releases_data = fetch_with_retry(releases_url, token)
        if releases_data:
            for rel in releases_data:
                if not include_prereleases and rel.get("prerelease"):
                    continue
                if rel.get("draft"):
                    continue
                normalized = normalize_release(rel, full_name)
                if normalized:
                    release_key = f"{full_name}@{normalized['version']}"
                    if release_key not in seen_releases:
                        seen_releases.add(release_key)
                        all_releases.append(normalized)

        time.sleep(delay)

    # Deterministic sorting
    all_repos.sort(key=lambda r: r.get("full_name", ""))
    all_releases.sort(key=lambda r: (r.get("published_at", "") or ""), reverse=True)

    return all_repos, all_releases


def save_repos(repos: list[dict]) -> Path:
    REPO_META_DIR.mkdir(parents=True, exist_ok=True)
    collection_date = utc_now().date().isoformat()
    output = {
        "meta": {
            "source": "GitHub",
            "collectedAt": utc_now().isoformat(),
            "count": len(repos),
        },
        "repositories": repos,
    }
    output_path = REPO_META_DIR / f"{collection_date}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return output_path


def save_releases(releases: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    collection_date = utc_now().date().isoformat()
    output = {
        "meta": {
            "source": "GitHub",
            "collectedAt": utc_now().isoformat(),
            "count": len(releases),
        },
        "releases": releases,
    }
    output_path = OUTPUT_DIR / f"{collection_date}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect GitHub repository metadata and releases.")
    parser.add_argument("--token", help="GitHub personal access token (optional)")
    args = parser.parse_args()

    token = args.token or get_github_token()

    print()
    print("TechPulse — GitHub Collector")
    print("=" * 32)
    print()

    try:
        config = load_config()
        repos, releases = collect_repos(config, token)
        repo_path = save_repos(repos)
        releases_path = save_releases(releases)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Collection completed successfully.")
    print(f"Repositories: {len(repos)}")
    print(f"Releases    : {len(releases)}")
    print(f"Repos output    : {repo_path}")
    print(f"Releases output : {releases_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())