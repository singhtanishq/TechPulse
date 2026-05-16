"""
TechPulse — Processor Utilities

Shared utilities for data processing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
NORMALIZED_DIR = DATA_DIR / "normalized"
GENERATED_DIR = PROJECT_ROOT / "generated"


def utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON file safely."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(data: dict[str, Any], path: Path) -> Path:
    """Save JSON with deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path


def get_latest_file(directory: Path, pattern: str = "*.json") -> Path | None:
    """Get the most recent JSON file in a directory."""
    files = list(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def format_date(date_obj: datetime | str) -> str:
    """Format date for display (e.g., '18 SEP 2026')."""
    if isinstance(date_obj, str):
        date_obj = parse_iso_datetime(date_obj)
    if not date_obj:
        return ""
    return date_obj.strftime("%d %b %Y").upper()


def format_relative_date(date_obj: datetime | str) -> str:
    """Format relative date (Today, Yesterday, X days ago)."""
    if isinstance(date_obj, str):
        date_obj = parse_iso_datetime(date_obj)
    if not date_obj:
        return ""

    now = utc_now()
    today = now.date()
    target_date = date_obj.date()
    delta = (today - target_date).days

    if delta == 0:
        return "Today"
    elif delta == 1:
        return "Yesterday"
    elif delta < 7:
        return f"{delta} days ago"
    else:
        return format_date(date_obj)


SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "NONE": 4,
    None: 5,
}


def sort_by_severity(items: list[dict], severity_key: str = "severity") -> list[dict]:
    """Sort items by severity (CRITICAL first)."""
    return sorted(items, key=lambda x: SEVERITY_ORDER.get(x.get(severity_key), 99))


def deduplicate_by_key(items: list[dict], key: str) -> list[dict]:
    """Deduplicate list of dicts by a key, keeping first occurrence."""
    seen = set()
    result = []
    for item in items:
        val = item.get(key)
        if val and val not in seen:
            seen.add(val)
            result.append(item)
    return result