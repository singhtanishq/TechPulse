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
    Re-running for the same date with identical records and identical
    metadata does not rewrite the output files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.parse
import urllib.request

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from processors.utils import ist_today, parse_iso_datetime, parse_ist_date  # noqa: E402


GITHUB_API_BASE = "https://api.github.com"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "scripts" / "config" / "github.json"

REPO_META_DIR = PROJECT_ROOT / "data" / "opensource"
RELEASES_DIR = PROJECT_ROOT / "data" / "releases"

DEFAULT_TIMEOUT = 30
MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2
RATE_LIMIT_DELAY = 1
MAX_RESPONSE_BYTES = 20 * 1024 * 1024

GITHUB_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)


def load_config() -> dict[str, Any]:
    """Load and validate GitHub configuration."""
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if not isinstance(config, dict):
        raise ValueError(
            "GitHub configuration must be a JSON object."
        )

    repositories = config.get(
        "tracked_repositories",
        [],
    )

    if not isinstance(repositories, list):
        raise ValueError(
            "tracked_repositories must be a list."
        )

    collection = config.get(
        "collection",
        {},
    )

    if not isinstance(collection, dict):
        raise ValueError(
            "collection must be a JSON object."
        )

    return config


def get_token() -> str | None:
    """Return an optional GitHub token from the environment."""
    return (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or None
    )


class GitHubError(Exception):
    """Fatal GitHub API error for a single request."""


class RateLimited(GitHubError):
    """GitHub API rate limit exhausted."""


def _retry_after_seconds(
    value: str | None,
) -> int | None:
    """Parse Retry-After as seconds or an HTTP date."""
    if not value:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        seconds = int(value)
        return max(0, min(seconds, 120))
    except ValueError:
        pass

    try:
        retry_at = datetime.fromtimestamp(
            0,
            tz=timezone.utc,
        )

        try:
            import email.utils

            retry_at = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if retry_at is None:
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(
                tzinfo=timezone.utc
            )

        seconds = int(
            (
                retry_at.astimezone(timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds()
        )

        return max(0, min(seconds, 120))

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _retry_delay_seconds(
    attempt: int,
    retry_after: str | None = None,
) -> int:
    """Calculate a bounded retry delay."""
    retry_after_seconds = _retry_after_seconds(
        retry_after
    )

    if retry_after_seconds is not None:
        return retry_after_seconds

    return RETRY_BACKOFF_BASE ** attempt * 2


def _read_response_body(response: Any) -> bytes:
    """Read a response while enforcing a maximum response size."""

    headers = getattr(
        response,
        "headers",
        {},
    )

    content_length = headers.get(
        "Content-Length"
    )

    if content_length:
        try:
            declared_size = int(content_length)

            if declared_size > MAX_RESPONSE_BYTES:
                raise GitHubError(
                    "GitHub API response is too large."
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = response.read(64 * 1024)

        if not chunk:
            break

        total_size += len(chunk)

        if total_size > MAX_RESPONSE_BYTES:
            raise GitHubError(
                "GitHub API response exceeded the maximum "
                "allowed size."
            )

        chunks.append(chunk)

    return b"".join(chunks)


def api_get(
    url: str,
    token: str | None,
) -> dict[str, Any] | list[Any]:
    """Perform a GET request against the GitHub API."""

    headers = {
        "User-Agent": (
            "TechPulse/1.0 "
            "(+https://github.com/singhtanishq/TechPulse)"
        ),
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

    last_error: Exception | None = None
    retry_after: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        if attempt > 0:
            wait = _retry_delay_seconds(
                attempt,
                retry_after,
            )

            print(
                f"    Retrying in {wait}s "
                f"(attempt {attempt + 1}/{MAX_ATTEMPTS})..."
            )

            if wait > 0:
                time.sleep(wait)

            retry_after = None

        request = urllib.request.Request(
            url,
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=DEFAULT_TIMEOUT,
            ) as response:
                status = getattr(
                    response,
                    "status",
                    200,
                )
                raw = _read_response_body(response)

            if status != 200:
                last_error = GitHubError(
                    f"GitHub API returned HTTP {status}"
                )
                continue

            try:
                payload = json.loads(
                    raw.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise GitHubError(
                    "GitHub API returned invalid JSON."
                ) from exc

            if not isinstance(
                payload,
                (dict, list),
            ):
                raise GitHubError(
                    "GitHub API returned an invalid "
                    "JSON response shape."
                )

            return payload

        except urllib.error.HTTPError as exc:
            remaining = (
                exc.headers.get("x-ratelimit-remaining")
                if exc.headers
                else None
            )

            retry_after = (
                exc.headers.get("Retry-After")
                if exc.headers
                else None
            )

            if (
                exc.code == 429
                or remaining == "0"
                or retry_after
            ):
                raise RateLimited(
                    "GitHub API rate limit exhausted "
                    "(set GITHUB_TOKEN to raise limits)."
                ) from exc

            if exc.code == 404:
                raise GitHubError(
                    "Repository not found (HTTP 404)."
                ) from exc

            if 500 <= exc.code < 600:
                print(
                    f"    GitHub server error ({exc.code})."
                )

                last_error = GitHubError(
                    f"GitHub API returned HTTP "
                    f"{exc.code}: {exc.reason}"
                )
                continue

            if exc.code == 403:
                raise GitHubError(
                    f"GitHub API returned HTTP 403: "
                    f"{exc.reason}"
                ) from exc

            raise GitHubError(
                f"GitHub API returned HTTP "
                f"{exc.code}: {exc.reason}"
            ) from exc

        except urllib.error.URLError as exc:
            print(
                f"    Network error: {exc.reason}"
            )

            last_error = GitHubError(
                f"Unable to reach GitHub API: "
                f"{exc.reason}"
            )
            continue

        except TimeoutError:
            print(
                "    GitHub API request timed out."
            )

            last_error = GitHubError(
                "GitHub API request timed out."
            )
            continue

        except GitHubError:
            raise

        except Exception as exc:
            print(
                f"    Unexpected error: {exc}"
            )

            last_error = GitHubError(
                f"Unexpected GitHub error: {exc}"
            )
            continue

    raise GitHubError(
        f"Request failed after {MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    ) from last_error


def _validate_repo_config(
    repo_config: Any,
) -> tuple[str, str, str] | None:
    """Validate one tracked repository configuration entry."""

    if not isinstance(
        repo_config,
        dict,
    ):
        return None

    owner = repo_config.get("owner")
    repo = repo_config.get("repo")
    category = repo_config.get(
        "category",
        "general",
    )

    if not isinstance(owner, str):
        return None

    if not isinstance(repo, str):
        return None

    if not isinstance(category, str):
        category = "general"

    owner = owner.strip()
    repo = repo.strip()
    category = category.strip() or "general"

    if not owner or not repo:
        return None

    if not GITHUB_NAME_PATTERN.fullmatch(
        owner
    ):
        return None

    if not GITHUB_NAME_PATTERN.fullmatch(
        repo
    ):
        return None

    return owner, repo, category


def _github_repo_path(
    owner: str,
    repo: str,
) -> str:
    """Build a safely encoded GitHub repository path."""
    encoded_owner = urllib.parse.quote(
        owner,
        safe=".-_",
    )
    encoded_repo = urllib.parse.quote(
        repo,
        safe=".-_",
    )

    return (
        f"{GITHUB_API_BASE}/repos/"
        f"{encoded_owner}/{encoded_repo}"
    )


def normalize_repo(
    repo_data: dict[str, Any],
    category: str,
) -> dict[str, Any]:
    """Normalize repository metadata."""

    owner_data = repo_data.get(
        "owner"
    )

    if not isinstance(
        owner_data,
        dict,
    ):
        owner_data = {}

    archived = repo_data.get(
        "archived"
    )

    if not isinstance(
        archived,
        bool,
    ):
        archived = False

    return {
        "name": repo_data.get("name"),
        "full_name": repo_data.get("full_name"),
        "owner": owner_data.get("login"),
        "url": repo_data.get("html_url"),
        "description": repo_data.get("description"),
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "open_issues": repo_data.get(
            "open_issues_count"
        ),
        "language": repo_data.get("language"),
        "category": category,
        "default_branch": repo_data.get(
            "default_branch"
        ),
        "created_at": repo_data.get(
            "created_at"
        ),
        "updated_at": repo_data.get(
            "updated_at"
        ),
        "pushed_at": repo_data.get(
            "pushed_at"
        ),
        "archived": archived,
        "source": "GitHub",
    }


def _repo_record_is_usable(
    record: dict[str, Any],
    expected_full_name: str,
) -> bool:
    """Validate the minimum repository fields required downstream."""

    full_name = record.get(
        "full_name"
    )
    owner = record.get(
        "owner"
    )
    url = record.get(
        "url"
    )
    name = record.get(
        "name"
    )

    if not all(
        isinstance(value, str)
        and value.strip()
        for value in (
            full_name,
            owner,
            url,
            name,
        )
    ):
        return False

    if full_name.lower() != expected_full_name.lower():
        return False

    if not str(url).startswith(
        "https://github.com/"
    ):
        return False

    return True


def normalize_release(
    release_data: dict[str, Any],
    repo_full_name: str,
) -> dict[str, Any] | None:
    """
    Normalize a release.

    Prereleases and drafts are excluded:
    TechPulse tracks stable releases to keep the daily
    signal clean.
    """

    if not isinstance(
        release_data,
        dict,
    ):
        return None

    if release_data.get("draft"):
        return None

    if release_data.get("prerelease"):
        return None

    tag_name = release_data.get(
        "tag_name"
    )
    published_at = release_data.get(
        "published_at"
    )

    if not isinstance(
        tag_name,
        str,
    ):
        return None

    if not isinstance(
        published_at,
        str,
    ):
        return None

    tag_name = tag_name.strip()
    published_at = published_at.strip()

    if not tag_name or not published_at:
        return None

    # Validate the timestamp but preserve GitHub's original
    # representation in the output.
    if parse_iso_datetime(
        published_at
    ) is None:
        return None

    if "/" not in repo_full_name:
        return None

    project = repo_full_name.split(
        "/",
        1,
    )[1]

    return {
        "project": project,
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
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, str]],
]:
    """
    Collect metadata and releases for all tracked repositories.

    Returns:
        (repos, releases, failures)

    failures is a list of:
        {"repository": "...", "error": "..."}

    Partial results are preserved.
    """

    if not isinstance(
        config,
        dict,
    ):
        raise ValueError(
            "GitHub configuration must be an object."
        )

    repos_config = config.get(
        "tracked_repositories",
        [],
    )

    collection_config = config.get(
        "collection",
        {},
    )

    if not isinstance(
        repos_config,
        list,
    ):
        raise ValueError(
            "tracked_repositories must be a list."
        )

    if not isinstance(
        collection_config,
        dict,
    ):
        raise ValueError(
            "collection must be an object."
        )

    raw_max_releases = collection_config.get(
        "max_releases_per_repo",
        5,
    )

    raw_delay = collection_config.get(
        "rate_limit_delay_seconds",
        1,
    )

    try:
        max_releases = int(
            raw_max_releases
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "max_releases_per_repo must be an integer."
        ) from exc

    if max_releases < 0:
        raise ValueError(
            "max_releases_per_repo cannot be negative."
        )

    try:
        delay = float(raw_delay)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "rate_limit_delay_seconds must be numeric."
        ) from exc

    if delay < 0:
        raise ValueError(
            "rate_limit_delay_seconds cannot be negative."
        )

    all_repos: list[dict[str, Any]] = []
    all_releases: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    seen_releases: set[str] = set()

    rate_limit_aborted = False

    for index, repo_config in enumerate(
        repos_config
    ):
        validated = _validate_repo_config(
            repo_config
        )

        if validated is None:
            failures.append(
                {
                    "repository": str(repo_config),
                    "error": "Invalid config entry",
                }
            )
            continue

        owner, repo, category = validated
        full_name = f"{owner}/{repo}"

        print(
            f"Fetching {full_name}..."
        )

        if rate_limit_aborted:
            failures.append(
                {
                    "repository": full_name,
                    "error": (
                        "Skipped: GitHub rate limit "
                        "exhausted earlier in run"
                    ),
                }
            )
            continue

        repo_url = _github_repo_path(
            owner,
            repo,
        )

        try:
            # -------------------------------------------------------- #
            # Repository metadata
            # -------------------------------------------------------- #

            repo_data = api_get(
                repo_url,
                token,
            )

            if not isinstance(
                repo_data,
                dict,
            ):
                raise GitHubError(
                    "GitHub repository endpoint "
                    "returned an unexpected response shape."
                )

            normalized_repo = normalize_repo(
                repo_data,
                category,
            )

            if not _repo_record_is_usable(
                normalized_repo,
                full_name,
            ):
                raise GitHubError(
                    "GitHub repository response was "
                    "missing required fields or did "
                    "not match the requested repository."
                )

            all_repos.append(
                normalized_repo
            )

            if delay > 0:
                time.sleep(delay)

            # -------------------------------------------------------- #
            # Releases
            # -------------------------------------------------------- #

            if max_releases > 0:
                releases_url = (
                    f"{repo_url}/releases"
                    f"?per_page={max_releases}"
                )

                releases_data = api_get(
                    releases_url,
                    token,
                )

                if not isinstance(
                    releases_data,
                    list,
                ):
                    raise GitHubError(
                        "GitHub releases endpoint "
                        "returned an unexpected response shape."
                    )

                for release in releases_data:
                    normalized = normalize_release(
                        release,
                        full_name,
                    )

                    if normalized is None:
                        continue

                    key = (
                        f"{full_name}@"
                        f"{normalized['version']}"
                    )

                    if key in seen_releases:
                        continue

                    seen_releases.add(key)
                    all_releases.append(
                        normalized
                    )

        except RateLimited as exc:
            print(
                f"    {exc}"
            )

            failures.append(
                {
                    "repository": full_name,
                    "error": str(exc),
                }
            )

            rate_limit_aborted = True
            continue

        except GitHubError as exc:
            print(
                f"    Failed: {exc}"
            )

            failures.append(
                {
                    "repository": full_name,
                    "error": str(exc),
                }
            )
            continue

        if delay > 0 and index < len(
            repos_config
        ) - 1:
            time.sleep(delay)

    # Deterministic ordering.
    all_repos.sort(
        key=lambda r: (
            r.get("full_name")
            or ""
        ).lower()
    )

    all_releases.sort(
        key=lambda r: (
            r.get("published_at")
            or "",
            r.get("repository")
            or "",
            r.get("version")
            or "",
        ),
        reverse=True,
    )

    return (
        all_repos,
        all_releases,
        failures,
    )


def records_fingerprint(
    data: Any,
) -> str:
    """Return a stable fingerprint of JSON-compatible data."""
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def metadata_for_idempotency(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Return metadata fields that affect snapshot correctness.

    collectedAt is deliberately excluded because it changes only when
    the snapshot actually needs to be rewritten.
    """

    meta = payload.get(
        "meta",
        {}
    )

    if not isinstance(
        meta,
        dict,
    ):
        return {}

    return {
        key: value
        for key, value in meta.items()
        if key != "collectedAt"
    }


def save_json_idempotent(
    directory: Path,
    snapshot_date: str,
    payload: dict[str, Any],
    records_key: str,
) -> Path:
    """
    Write a dated JSON file unless its records and relevant metadata
    are unchanged.
    """

    if parse_ist_date(
        snapshot_date
    ) is None:
        raise ValueError(
            "snapshot_date must be in YYYY-MM-DD format."
        )

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "payload must be a JSON object."
        )

    if records_key not in payload:
        raise ValueError(
            f"payload missing records key: {records_key}"
        )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        directory
        / f"{snapshot_date}.json"
    )

    new_records = records_fingerprint(
        payload[records_key]
    )

    new_metadata = records_fingerprint(
        metadata_for_idempotency(
            payload
        )
    )

    if output_path.exists():
        try:
            existing = json.loads(
                output_path.read_text(
                    encoding="utf-8"
                )
            )

            existing_records = records_fingerprint(
                existing.get(
                    records_key,
                    [],
                )
            )

            existing_metadata = records_fingerprint(
                metadata_for_idempotency(
                    existing
                )
            )

            if (
                existing_records == new_records
                and existing_metadata == new_metadata
            ):
                print(
                    f"Records and metadata unchanged "
                    f"for {snapshot_date}; keeping "
                    "existing file."
                )
                return output_path

        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
        ):
            # Corrupt or structurally unusable existing
            # file: overwrite with fresh data.
            pass

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            payload,
            f,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        f.write("\n")

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect GitHub repository metadata "
            "and releases."
        )
    )

    parser.add_argument(
        "--date",
        type=str,
        help=(
            "Reporting date label (YYYY-MM-DD, "
            "IST edition). Default: current "
            "reporting date."
        ),
    )

    args = parser.parse_args()

    if args.date:
        if parse_ist_date(
            args.date
        ) is None:
            parser.error(
                "--date must be in YYYY-MM-DD format."
            )

        snapshot_date = args.date
    else:
        snapshot_date = ist_today()

    token = get_token()

    auth_state = (
        "authenticated"
        if token
        else "unauthenticated "
        "(60 req/hour limit)"
    )

    print()
    print("TechPulse — GitHub Collector")
    print("=" * 32)
    print(
        f"Reporting date: {snapshot_date} "
        "(IST edition)"
    )
    print(
        f"Auth          : {auth_state}"
    )
    print()

    try:
        config = load_config()

        (
            repos,
            releases,
            failures,
        ) = collect_repos(
            config,
            token,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    collected_at = datetime.now(
        timezone.utc
    ).isoformat()

    repo_payload = {
        "meta": {
            "source": "GitHub",
            "collectedAt": collected_at,
            "reportingDate": snapshot_date,
            "count": len(repos),
            "failures": failures,
        },
        "repositories": repos,
    }

    release_payload = {
        "meta": {
            "source": "GitHub",
            "collectedAt": collected_at,
            "reportingDate": snapshot_date,
            "count": len(releases),
            "failures": failures,
        },
        "releases": releases,
    }

    repo_path = save_json_idempotent(
        REPO_META_DIR,
        snapshot_date,
        repo_payload,
        "repositories",
    )

    releases_path = save_json_idempotent(
        RELEASES_DIR,
        snapshot_date,
        release_payload,
        "releases",
    )

    print()
    print("Collection finished.")
    print(
        f"Repositories : {len(repos)}"
    )
    print(
        f"Releases     : {len(releases)}"
    )

    if failures:
        print(
            f"Failures     : {len(failures)}"
        )

        for failure in failures:
            print(
                f"  - {failure['repository']}: "
                f"{failure['error']}"
            )

    print(
        f"Repos output    : {repo_path}"
    )
    print(
        f"Releases output : {releases_path}"
    )
    print()

    # Exit non-zero only when nothing at all was collected.
    if not repos and not releases:
        print(
            "ERROR: No GitHub data could be collected.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())