from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.agents import router as agents_router
from app.api.tasks import router as tasks_router, global_router as tasks_global_router
from app.api.reviews import router as reviews_router
from app.api.models import router as models_router
from app.api.ws import router as ws_router
from app.api.versions import router as versions_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
app.include_router(tasks_router)
app.include_router(tasks_global_router)
app.include_router(reviews_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {"message": "Agent Collaboration Platform API"}
