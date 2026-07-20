import sys

# ── Windows UTF-8 safeguard ──────────────────────────────────────────────
# On Windows the default console encoding is GBK, which cannot encode many
# Unicode characters (e.g. the emojis CrewAI prints during execution). That
# raises UnicodeEncodeError and aborts the whole agent pipeline. Force UTF-8
# for stdout/stderr so third-party output (CrewAI, rich, etc.) never crashes,
# regardless of how uvicorn is launched.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Persisted merge-queued tasks survive a process restart and are resumed
    # by the bounded, project-serial merge scheduler.
    from app.services.execution_service import recover_merge_queue
    recover_merge_queue()
    yield


app = FastAPI(
    title="多 Agent 协作审查平台",
    version="0.1.0",
    lifespan=lifespan,
)

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
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # Git CLI
    try:
        import subprocess
        subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=5)
        checks["git"] = "ok"
    except Exception as e:
        checks["git"] = f"error: {e}"
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

    status_code = 200 if healthy else 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}, status_code
