"""Settings API — read and update application configuration.

Reads from / writes to the .env file alongside config.py.
Sensitive fields (API keys) are masked in responses.
"""

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings as app_settings

router = APIRouter(prefix="/api/settings", tags=["Settings"])

# Absolute path to the .env file at backend/.env
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


# ── Section definitions ──────────────────────────────────────────────────

SETTINGS_SECTIONS = [
    {
        "key": "api_keys",
        "label": "API 密钥",
        "fields": [
            {"key": "DEEPSEEK_API_KEY",  "label": "DeepSeek API Key",      "type": "password"},
            {"key": "ANTHROPIC_API_KEY", "label": "Anthropic API Key",     "type": "password"},
        ],
    },
    {
        "key": "api_endpoints",
        "label": "API 端点",
        "fields": [
            {"key": "DEEPSEEK_BASE_URL",   "label": "DeepSeek Base URL",    "type": "text"},
            {"key": "OPENCODE_SERVER_URL", "label": "OpenCode Server URL",  "type": "text"},
        ],
    },
    {
        "key": "workspace",
        "label": "工作空间",
        "fields": [
            {"key": "WORKSPACE_ROOT", "label": "Workspace 根目录", "type": "text"},
        ],
    },
]


def _mask(value: str | None) -> str:
    """Mask an API key: show first 4 and last 4 chars, middle replaced with ****."""
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "****" + value[-2:]
    return value[:4] + "****" + value[-4:]


def _read_env() -> dict[str, str]:
    """Parse the .env file into a dict."""
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _write_env(updates: dict[str, str]) -> None:
    """Update keys in the .env file. Existing keys are replaced; new keys appended."""
    if not _ENV_PATH.exists():
        raise HTTPException(status_code=500, detail=f".env file not found at {_ENV_PATH}")

    content = _ENV_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    for key, new_val in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.IGNORECASE)
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                lines[i] = f"{key}={new_val}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={new_val}")

    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Endpoints ────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    key: str
    value: str


@router.get("")
def get_settings():
    """Return all user-facing settings, grouped into sections.
    Sensitive fields (API keys) are masked.
    """
    env = _read_env()
    sections_out = []
    for sec in SETTINGS_SECTIONS:
        fields_out = []
        for f in sec["fields"]:
            raw = env.get(f["key"], getattr(app_settings, f["key"], ""))
            fields_out.append({
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "value": raw,
                "masked_value": _mask(raw) if f["type"] == "password" else raw,
            })
        sections_out.append({
            "key": sec["key"],
            "label": sec["label"],
            "fields": fields_out,
        })
    return {"sections": sections_out}


@router.post("")
def update_setting(req: SettingUpdate):
    """Update a single setting value. Writes to the .env file immediately.
    Requires backend restart for the change to take full effect.
    """
    allowed_keys = set()
    for sec in SETTINGS_SECTIONS:
        for f in sec["fields"]:
            allowed_keys.add(f["key"])

    if req.key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"Unknown setting key: {req.key!r}")

    _write_env({req.key: req.value})

    # Also update the in-memory settings object if possible
    if hasattr(app_settings, req.key):
        setattr(app_settings, req.key, req.value)

    # Audit: 配置变更（记录变更项，敏感密钥不记原文）。
    from app.services.audit_service import record as audit_record
    from app.models.models import AuditAction, AuditActorType
    is_secret = any(
        f["type"] == "password" for sec in SETTINGS_SECTIONS for f in sec["fields"] if f["key"] == req.key
    )
    audit_record(
        action=AuditAction.CONFIG_UPDATE,
        actor_type=AuditActorType.HUMAN,
        target_type="config",
        target_id=req.key,
        intent=f"更新配置 {req.key}",
        payload={"value": "***" if is_secret else req.value, "secret": is_secret},
    )

    return {
        "key": req.key,
        "value": req.value,
        "masked_value": _mask(req.value) if any(
            f["type"] == "password" for sec in SETTINGS_SECTIONS for f in sec["fields"] if f["key"] == req.key
        ) else req.value,
        "message": "已保存，部分设置需重启后端生效",
    }
