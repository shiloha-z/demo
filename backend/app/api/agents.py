import shutil

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Agent, AgentStatus, Task, TaskStatus, Review, ReviewStatus

router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ── Schemas ───────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., min_length=1, max_length=100)
    model: str = Field(default="deepseek-chat")
    runner_type: str = Field(default="crewai")
    system_prompt: str = Field(default="")


class AgentResponse(BaseModel):
    id: int
    name: str
    role: str
    model: str
    runner_type: str = "crewai"
    system_prompt: str
    status: str
    total_tasks: int = 0
    approved_tasks: int = 0
    approval_rate: str | None = None
    current_task_id: int | None = None
    current_task_title: str | None = None
    last_task_status: str | None = None

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[AgentResponse])
def list_agents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agents = db.query(Agent).all()
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
            system_prompt=a.system_prompt,
            status=a.status.value if hasattr(a.status, 'value') else str(a.status),
            total_tasks=total_tasks,
            approved_tasks=approved_tasks,
            approval_rate=approval_rate,
            current_task_id=current_task_id,
            current_task_title=current_task_title,
            last_task_status=last_task_status,
        ))
    return result


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
        status=AgentStatus.IDLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentResponse.model_validate(agent)


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
    db.delete(agent)
    db.commit()
    return {"message": "Deleted"}
