"""Get available LLM models from the configured provider."""

import os
import httpx
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["Models"])

# Hardcoded model lists for non-API-fetchable backends
ANTHROPIC_MODELS = [
    {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 5"},
    {"id": "claude-opus-4-20250514", "name": "Claude Opus 4"},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
]

DEEPSEEK_FALLBACK = [
    {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)", "description": "通用对话模型"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "description": "深度推理模型"},
]


@router.get("/models")
async def list_models(runner_type: str = Query(default="crewai")):
    """Fetch available models for a given runner type.

    - crewai / opencode: fetches from DeepSeek API (or any OpenAI-compatible endpoint)
    - claude_code: returns Anthropic model list
    """
    if runner_type == "claude_code":
        return {"models": ANTHROPIC_MODELS}

    # Default: fetch from DeepSeek (OpenAI-compatible) API
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    if not api_key:
        return {"models": DEEPSEEK_FALLBACK}

    url = base_url.rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                model_list = data.get("data", data.get("models", []))
                return {
                    "models": [
                        {"id": m.get("id", m.get("model", "unknown")), "name": m.get("id", "unknown")}
                        for m in model_list
                    ]
                }
    except Exception:
        pass

    return {"models": DEEPSEEK_FALLBACK}
