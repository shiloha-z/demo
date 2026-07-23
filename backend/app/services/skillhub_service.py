"""Server-side client for the SkillHub skills catalog.

The SkillHub API key always stays in backend settings; browser clients call
our API routes and never receive the key.
"""

from typing import Any

import httpx

from app.core.config import settings

BASE_URL = "https://www.skillhub.club/api/v1"
REQUEST_TIMEOUT_SECONDS = 15.0


class SkillHubError(RuntimeError):
    """A usable error message for an unavailable SkillHub request."""


def _api_key() -> str:
    key = settings.SKILLHUB_API_KEY.strip()
    if not key:
        raise SkillHubError("SkillHub API Key is not configured")
    return key


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Call SkillHub and normalize errors without exposing credentials."""
    try:
        response = httpx.request(
            method,
            f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {_api_key()}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise SkillHubError("Unable to reach SkillHub") from exc

    if response.status_code >= 400:
        try:
            body = response.json()
            detail = body.get("message") or body.get("error") if isinstance(body, dict) else ""
        except ValueError:
            detail = ""
        if response.status_code == 401:
            msg = detail or "the API key was rejected by SkillHub"
            raise SkillHubError(f"SkillHub API Key was rejected: {msg}")
        if response.status_code == 429:
            raise SkillHubError("SkillHub rate limit reached; please retry shortly")
        raise SkillHubError(detail or f"SkillHub returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SkillHubError("SkillHub returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise SkillHubError("SkillHub returned an unexpected response")
    return payload


def configured() -> bool:
    """Whether the backend has a SkillHub key available."""
    return bool(settings.SKILLHUB_API_KEY.strip())


def search_skills(query: str, *, limit: int = 20, category: str = "", method: str = "hybrid") -> dict[str, Any]:
    body: dict[str, Any] = {"query": query, "limit": limit, "method": method}
    if category:
        body["category"] = category
    return _request("POST", "/skills/search", json=body)


def browse_catalog(*, limit: int = 20, offset: int = 0, sort: str = "score", category: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "offset": offset, "sort": sort}
    if category:
        params["category"] = category
    return _request("GET", "/skills/catalog", params=params)
