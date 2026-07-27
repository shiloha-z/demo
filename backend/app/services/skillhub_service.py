"""Skill catalog backed by the Agent Skills Hub open registry.

Fetches the skills index and individual SKILL.md files from the public
GitHub repository at https://github.com/agent-skills-hub/agent-skills-hub.

The index is cached in-memory with a TTL so repeated UI browses don't
hammer GitHub's raw CDN.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

BASE_URL = "https://raw.githubusercontent.com/agent-skills-hub/agent-skills-hub/main"
INDEX_URL = f"{BASE_URL}/skills_index.json"
REQUEST_TIMEOUT_SECONDS = 15.0

# ── In-memory cache ────────────────────────────────────────────────────────
_index_cache: list[dict[str, Any]] | None = None
_index_cache_ts: float = 0.0
_INDEX_CACHE_TTL_SECONDS = 300  # 5 minutes


class SkillHubError(RuntimeError):
    """A usable error message for an unavailable skill catalog request."""


def _fetch_json(url: str) -> Any:
    """GET *url*, returning parsed JSON or raising SkillHubError."""
    try:
        resp = httpx.get(url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SkillHubError("Unable to reach Agent Skills Hub") from exc

    if resp.status_code >= 400:
        raise SkillHubError(
            f"Agent Skills Hub returned HTTP {resp.status_code}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SkillHubError("Agent Skills Hub returned an invalid response") from exc
    return payload


def _load_index() -> list[dict[str, Any]]:
    """Return the full skill index, refreshing the cache when stale."""
    global _index_cache, _index_cache_ts
    now = time.time()
    if _index_cache is not None and (now - _index_cache_ts) < _INDEX_CACHE_TTL_SECONDS:
        return _index_cache

    raw = _fetch_json(INDEX_URL)
    if not isinstance(raw, list):
        raise SkillHubError("Agent Skills Hub index has an unexpected format")

    _index_cache = raw
    _index_cache_ts = now
    return raw


def _index_to_browse_result(
    entries: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Slice *entries* into a catalog page in the format the frontend expects."""
    total = len(entries)
    page = entries[offset : offset + limit]
    return {
        "data": [
            {
                "id": e.get("id", ""),
                "name": e.get("name", e.get("id", "")),
                "description": e.get("description", ""),
                "category": e.get("category", ""),
                "source_url": (
                    f"{BASE_URL}/{e['path']}/SKILL.md" if e.get("path") else ""
                ),
            }
            for e in page
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── Public API (same signatures as before) ──────────────────────────────────

def configured() -> bool:
    """Agent Skills Hub is a public registry — always available."""
    return True


def search_skills(
    query: str,
    *,
    limit: int = 20,
    category: str = "",
    method: str = "hybrid",
) -> dict[str, Any]:
    """Search the Agent Skills Hub index by keyword."""
    _ = method  # accepted for API compatibility
    index = _load_index()
    ql = query.lower()

    def _matches(e: dict[str, Any]) -> bool:
        if category and e.get("category", "") != category:
            return False
        haystack = " ".join(
            str(e.get(k, ""))
            for k in ("name", "description", "category", "id")
        ).lower()
        return ql in haystack

    hits = [e for e in index if _matches(e)]
    return _index_to_browse_result(hits, limit=limit, offset=0)


def browse_catalog(
    *,
    limit: int = 20,
    offset: int = 0,
    sort: str = "score",
    category: str = "",
) -> dict[str, Any]:
    """Browse the Agent Skills Hub catalog."""
    _ = sort  # accepted for API compatibility
    index = _load_index()
    entries = index
    if category:
        entries = [e for e in entries if e.get("category", "") == category]
    return _index_to_browse_result(entries, limit=limit, offset=offset)


def fetch_skill_content(skill_id: str) -> str:
    """Fetch the full SKILL.md content for a skill by its id.

    Looks up the path in the index and fetches the raw markdown.
    """
    index = _load_index()
    entry = next((e for e in index if e.get("id") == skill_id), None)
    if not entry:
        raise SkillHubError(f"Skill not found: {skill_id}")
    path = entry.get("path", "")
    if not path:
        raise SkillHubError(f"Skill {skill_id} has no path in the index")
    url = f"{BASE_URL}/{path}/SKILL.md"
    try:
        resp = httpx.get(url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SkillHubError("Unable to fetch skill content") from exc
    if resp.status_code >= 400:
        raise SkillHubError(f"Skill content fetch returned HTTP {resp.status_code}")
    return resp.text
