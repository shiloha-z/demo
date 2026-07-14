from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Project, Agent, Task, TaskStatus, AgentStatus

router = APIRouter(prefix="/api/projects/{project_id}/tasks", tags=["Tasks"])


# ── Schemas ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    agent_id: int


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    agent_id: int
    project_id: int

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[TaskResponse])
def list_tasks(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.id.desc()).all()
    return [TaskResponse.model_validate(t) for t in tasks]


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: int,
    req: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Validate agent exists (globally)
    agent = db.query(Agent).filter(Agent.id == req.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task = Task(
        agent_id=req.agent_id,
        project_id=project_id,
        title=req.title,
        description=req.description,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Update agent status
    agent.status = AgentStatus.WORKING
    db.commit()

    # Run agent pipeline in background
    from app.services.agent_runner import run_agent_pipeline
    background_tasks.add_task(run_agent_pipeline, task.id)

    return TaskResponse.model_validate(task)
