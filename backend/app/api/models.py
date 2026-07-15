"""Get available LLM models from the configured provider."""

import httpx
from fastapi import APIRouter, Query

from app.core.config import settings

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

    Response includes `source` ("api" | "static") and `count` so the frontend
    can show meaningful feedback.
    """
    if runner_type == "claude_code":
        return {"models": ANTHROPIC_MODELS, "source": "static", "count": len(ANTHROPIC_MODELS)}

    # Default: fetch from DeepSeek (OpenAI-compatible) API
    api_key = settings.DEEPSEEK_API_KEY
    base_url = settings.DEEPSEEK_BASE_URL

    if not api_key:
        return {"models": DEEPSEEK_FALLBACK, "source": "fallback",
                "count": len(DEEPSEEK_FALLBACK), "hint": "DEEPSEEK_API_KEY 未配置"}

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
                models = [
                    {"id": m.get("id", m.get("model", "unknown")), "name": m.get("id", "unknown")}
                    for m in model_list
                ]
                return {"models": models, "source": "api", "count": len(models)}
            else:
                return {"models": DEEPSEEK_FALLBACK, "source": "fallback",
                        "count": len(DEEPSEEK_FALLBACK),
                        "hint": f"API 返回状态码 {resp.status_code}"}
    except Exception as e:
        return {"models": DEEPSEEK_FALLBACK, "source": "fallback",
                "count": len(DEEPSEEK_FALLBACK),
                "hint": f"API 请求失败: {str(e)[:100]}"}
