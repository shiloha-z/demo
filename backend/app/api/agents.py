from fastapi import APIRouter, Depends, HTTPException, status
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
    system_prompt: str = Field(default="")


class AgentResponse(BaseModel):
    id: int
    name: str
    role: str
    model: str
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
        system_prompt=req.system_prompt,
        status=AgentStatus.IDLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
    return {"message": "Deleted"}
