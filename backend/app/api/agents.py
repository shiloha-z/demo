import shutil

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.pagination import paginate
from app.models.models import User, Agent, AgentStatus, Task, TaskStatus, QualityGateRun, Review, ReviewStatus, ReviewVote, ReviewReviewer, ReviewRound, Version

router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ── Schemas ───────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., min_length=1, max_length=100)
    model: str = Field(default="deepseek-chat")
    runner_type: str = Field(default="crewai")
    system_prompt: str = Field(default="")
    enable_planning: bool = Field(default=False)
    max_subtasks: int = Field(default=6, ge=1, le=20)


class AgentImport(BaseModel):
    """Portable Agent configuration exported by this application."""
    format: str = Field(default="agent-pool-export")
    version: int = Field(default=1)
    agent: AgentCreate


class AgentResponse(BaseModel):
    id: int
    name: str
    role: str
    model: str
    runner_type: str = "crewai"
    system_prompt: str
    enable_planning: bool = False
    max_subtasks: int = 6
    status: str
    total_tasks: int = 0
    approved_tasks: int = 0
    approval_rate: str | None = None
    current_task_id: int | None = None
    current_task_title: str | None = None
    last_task_status: str | None = None
    creator_id: int
    creator_name: str = ""
    is_creator: bool = False

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("")
def list_agents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Agents are a shared pool. Project-level permission is enforced when a
    # user assigns one to a task; ownership only controls deletion.
    q = db.query(Agent).options(joinedload(Agent.creator)).order_by(Agent.id.desc())
    agents, paging = paginate(q, page, page_size)
    result = []
    for a in agents:
        # Task stats
        total_tasks = db.query(func.count(Task.id)).filter(Task.agent_id == a.id).scalar() or 0
        approved_tasks = db.query(func.count(Task.id)).filter(
            Task.agent_id == a.id, Task.status == TaskStatus.APPROVED
        ).scalar() or 0
        approval_rate = f"{round(approved_tasks / total_tasks * 100)}%" if total_tasks > 0 else None

        # Current task (if working)
        current_task_id = None
        current_task_title = None
        last_task_status = None
        if a.status == AgentStatus.WORKING:
            current = (
                db.query(Task)
                .filter(Task.agent_id == a.id, Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
                .order_by(Task.id.desc())
                .first()
            )
            if current:
                current_task_id = current.id
                current_task_title = current.title
        else:
            # Last task result
            last_task = (
                db.query(Task)
                .filter(Task.agent_id == a.id)
                .order_by(Task.id.desc())
                .first()
            )
            if last_task:
                last_task_status = last_task.status.value if hasattr(last_task.status, 'value') else str(last_task.status)

        result.append(AgentResponse(
            id=a.id,
            name=a.name,
            role=a.role,
            model=a.model,
            runner_type=a.runner_type or "crewai",
            system_prompt=a.system_prompt if a.creator_id == user.id else "",
            enable_planning=bool(a.enable_planning),
            max_subtasks=a.max_subtasks,
            status=a.status.value if hasattr(a.status, 'value') else str(a.status),
            total_tasks=total_tasks,
            approved_tasks=approved_tasks,
            approval_rate=approval_rate,
            current_task_id=current_task_id,
            current_task_title=current_task_title,
            last_task_status=last_task_status,
            creator_id=a.creator_id,
            creator_name=a.creator.display_name or a.creator.username if a.creator else "",
            is_creator=a.creator_id == user.id,
        ))
    return {"items": result, **paging}


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    req: AgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = Agent(
        creator_id=user.id,
        name=req.name,
        role=req.role,
        model=req.model,
        runner_type=req.runner_type,
        system_prompt=req.system_prompt,
        enable_planning=req.enable_planning,
        max_subtasks=req.max_subtasks,
        status=AgentStatus.IDLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    from app.api.ws import broadcast_sync
    broadcast_sync("agent_update", {"id": agent.id, "status": "created"})
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        model=agent.model,
        runner_type=agent.runner_type or "crewai",
        system_prompt=agent.system_prompt,
        enable_planning=agent.enable_planning,
        max_subtasks=agent.max_subtasks,
        status=agent.status.value,
        creator_id=user.id,
        creator_name=user.display_name or user.username,
        is_creator=True,
    )


@router.get("/{agent_id}/export")
def export_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export an Agent's reusable configuration without runtime or task data."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Only the Agent creator can export its private configuration")

    return {
        "format": "agent-pool-export",
        "version": 1,
        "agent": {
            "name": agent.name,
            "role": agent.role,
            "model": agent.model,
            "runner_type": agent.runner_type or "crewai",
            "system_prompt": agent.system_prompt or "",
            "enable_planning": bool(agent.enable_planning),
            "max_subtasks": agent.max_subtasks,
        },
    }


@router.post("/import", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def import_agent(
    req: AgentImport,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new Agent from a portable export owned by the importing user."""
    if req.format != "agent-pool-export" or req.version != 1:
        raise HTTPException(status_code=400, detail="Unsupported Agent export format or version")

    source = req.agent
    agent = Agent(
        creator_id=user.id,
        name=source.name,
        role=source.role,
        model=source.model,
        runner_type=source.runner_type,
        system_prompt=source.system_prompt,
        enable_planning=bool(getattr(source, "enable_planning", False)),
        max_subtasks=getattr(source, "max_subtasks", 6) or 6,
        status=AgentStatus.IDLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    from app.api.ws import broadcast_sync
    broadcast_sync("agent_update", {"id": agent.id, "status": "created"})
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        model=agent.model,
        runner_type=agent.runner_type or "crewai",
        system_prompt=agent.system_prompt,
        enable_planning=agent.enable_planning,
        max_subtasks=agent.max_subtasks,
        status=agent.status.value,
        creator_id=user.id,
        creator_name=user.display_name or user.username,
        is_creator=True,
    )


# Runner CLI detection table
_RUNNER_CLI: dict[str, str] = {
    "claude_code": "claude",
    "opencode": "opencode",
}

_RUNNER_INSTALL_HINTS: dict[str, str] = {
    "claude_code": "请安装 Claude Code CLI：https://claude.ai/code，然后运行 `claude` 完成认证",
    "opencode": "请安装 OpenCode CLI：https://opencode.ai 或 `pip install opencode-cli`",
}


@router.get("/check-runner")
def check_runner(runner_type: str = Query(..., description="Runner type to check")):
    """Check whether the required CLI for a runner type is available on PATH.

    Returns `available: true` if the CLI is found, otherwise `available: false`
    with an install hint.
    """
    if runner_type not in _RUNNER_CLI:
        # crewai or unknown — no CLI to check
        return {"available": True, "runner_type": runner_type, "checked": False}

    cli_name = _RUNNER_CLI[runner_type]
    found = shutil.which(cli_name) is not None
    return {
        "available": found,
        "runner_type": runner_type,
        "cli_name": cli_name,
        "checked": True,
        "hint": "" if found else _RUNNER_INSTALL_HINTS.get(runner_type, ""),
    }


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.creator_id != user.id:
        raise HTTPException(status_code=403, detail="只有 Agent 创建者才能删除")

    # Clean up associated records: review dependents → reviews → tasks
    task_ids = [
        row[0] for row in
        db.query(Task.id).filter(Task.agent_id == agent_id).all()
    ]
    if task_ids:
        db.query(QualityGateRun).filter(
            QualityGateRun.task_id.in_(task_ids)
        ).delete(synchronize_session=False)
        review_ids = [
            row[0] for row in
            db.query(Review.id).filter(Review.task_id.in_(task_ids)).all()
        ]
        if review_ids:
            db.query(ReviewVote).filter(ReviewVote.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(ReviewReviewer).filter(ReviewReviewer.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(ReviewRound).filter(ReviewRound.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(Version).filter(Version.review_id.in_(review_ids)).update(
                {Version.review_id: None}, synchronize_session=False
            )
            db.query(Review).filter(Review.id.in_(review_ids)).delete(synchronize_session=False)
        db.query(Task).filter(Task.agent_id == agent_id).delete(synchronize_session=False)

    db.delete(agent)
    db.commit()

    # Clean up agent-scoped memory (ChromaDB collection).
    try:
        from app.services import memory_service as mem
        mem.delete_agent_memory(agent_id)
    except Exception:
        pass

    # Notify clients about agent removal
    from app.api.ws import broadcast_sync
    broadcast_sync("agent_update", {"id": agent_id, "status": "deleted"})

    return {"message": "Deleted"}
