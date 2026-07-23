import sys

# ── Windows UTF-8 safeguard ──────────────────────────────────────────────
# On Windows the default console encoding is GBK, which cannot encode many
# Unicode characters (e.g. the emojis CrewAI prints during execution). That
# raises UnicodeEncodeError and aborts the whole agent pipeline. Force UTF-8
# for stdout/stderr so third-party output (CrewAI, rich, etc.) never crashes,
# regardless of how uvicorn is launched.
#
# Do not replace or wrap the stream object: test runners, IDEs and process
# supervisors own those streams and may use temporary capture files. Replacing
# them can close the owner's file when our wrapper is collected.
def _force_utf8(stream):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Some capture/proxy streams intentionally do not support reconfigure.
        # Keeping the original stream is safer than taking ownership of its
        # underlying buffer.
        pass
    return stream

sys.stdout = _force_utf8(sys.stdout)
sys.stderr = _force_utf8(sys.stderr)

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
from app.core.http_stability import install_http_stability
from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.agents import router as agents_router
from app.api.skills import router as skills_router
from app.api.tasks import router as tasks_router, global_router as tasks_global_router
from app.api.reviews import router as reviews_router
from app.api.models import router as models_router
from app.api.ws import router as ws_router
from app.api.versions import router as versions_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.members import router as members_router
from app.api.messages import router as messages_router
from app.api.audit import router as audit_router
from app.api.risk_dashboard import router as risk_dashboard_router
from app.api.admin import router as admin_router  # 调试用管理后台（无鉴权，仅本地）

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Process-local model calls cannot survive a restart. Repair their durable
    # state before accepting traffic, then resume persisted merge work.
    from app.services.execution_service import (
        recover_interrupted_agent_runs,
        recover_merge_queue,
    )
    recovered = recover_interrupted_agent_runs()
    recover_merge_queue()
    logger.info("Application ready; recovered_interrupted_tasks=%s", recovered)
    try:
        yield
    finally:
        from app.api.ws import manager
        await manager.shutdown()
        logger.info("Application shutdown complete")


app = FastAPI(
    title="多 Agent 协作审查平台",
    version="0.1.0",
    lifespan=lifespan,
)
install_http_stability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(versions_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(tasks_router)
app.include_router(tasks_global_router)
app.include_router(reviews_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(members_router)
app.include_router(messages_router)
app.include_router(audit_router)
app.include_router(risk_dashboard_router)
# 调试用管理后台（无鉴权，仅本地调试使用，生产需移除或加访问控制）
app.include_router(admin_router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {"message": "Agent Collaboration Platform API"}


@app.get("/api/health")
def health_check():
    """Readiness probe — verify DB, Git, and optional ChromaDB are reachable."""
    checks: dict[str, str] = {}
    healthy = True

    # Database
    try:
        from app.core.database import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error("Database readiness check failed", exc_info=e)
        checks["database"] = "error"
        healthy = False

    # Git CLI
    try:
        import subprocess
        subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=5)
        checks["git"] = "ok"
    except Exception as e:
        logger.error("Git readiness check failed", exc_info=e)
        checks["git"] = "error"
        healthy = False

    # ChromaDB (optional — degrade gracefully)
    try:
        from app.services import memory_service as mem
        if mem is not None and hasattr(mem, 'mem_ok') and not mem.mem_ok():
            checks["chromadb"] = "unavailable"
        else:
            checks["chromadb"] = "ok" if mem is not None else "not installed"
    except Exception:
        checks["chromadb"] = "not installed"

    status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


@app.get("/api/live")
def liveness_check():
    """Liveness probe: the event loop can accept and route requests."""
    return {"status": "ok"}
