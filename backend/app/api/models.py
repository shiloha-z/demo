"""Get available LLM models from the configured provider."""

import os
import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["Models"])


@router.get("/models")
async def list_models():
    """Fetch available models from the LLM provider's /models endpoint."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    if not api_key:
        # Return commonly known DeepSeek models as fallback
        return {
            "models": [
                {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)", "description": "通用对话模型"},
                {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "description": "深度推理模型"},
            ]
        }

    # Ensure base_url has no trailing slash, then append /v1/models
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

    # Fallback on error
    return {
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
        ]
    }
