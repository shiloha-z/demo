from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Project, Agent, Task, TaskStatus, AgentStatus, Review

router = APIRouter(prefix="/api/projects/{project_id}/tasks", tags=["Tasks"])

# Separate router for global task listing (no project_id in path)
global_router = APIRouter(prefix="/api/tasks", tags=["Tasks Global"])


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
    created_at: str | None = None
    agent_name: str | None = None
    project_name: str | None = None

    class Config:
        from_attributes = True


class TaskDetailResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    agent_id: int
    project_id: int
    created_at: str | None = None
    agent_name: str | None = None
    agent_role: str | None = None
    agent_model: str | None = None
    project_name: str | None = None
    review: dict | None = None

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

def _task_to_response(t: Task) -> TaskResponse:
    return TaskResponse(
        id=t.id,
        title=t.title,
        description=t.description,
        status=t.status.value if hasattr(t.status, 'value') else t.status,
        agent_id=t.agent_id,
        project_id=t.project_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
        agent_name=t.agent.name if t.agent else None,
        project_name=t.project.name if t.project else None,
    )


@router.get("", response_model=list[TaskResponse])
def list_tasks(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = (
        db.query(Task)
        .filter(Task.project_id == project_id)
        .options(joinedload(Task.agent), joinedload(Task.project))
        .order_by(Task.id.desc())
        .all()
    )
    return [_task_to_response(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.project_id == project_id)
        .options(joinedload(Task.agent), joinedload(Task.project))
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Find associated review
    review = db.query(Review).filter(Review.task_id == task.id).order_by(Review.id.desc()).first()

    return TaskDetailResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status.value if hasattr(task.status, 'value') else task.status,
        agent_id=task.agent_id,
        project_id=task.project_id,
        created_at=task.created_at.isoformat() if task.created_at else None,
        agent_name=task.agent.name if task.agent else None,
        agent_role=task.agent.role if task.agent else None,
        agent_model=task.agent.model if task.agent else None,
        project_name=task.project.name if task.project else None,
        review={
            "id": review.id,
            "diff_content": review.diff_content,
            "agent_review_summary": review.agent_review_summary,
            "status": review.status.value if hasattr(review.status, 'value') else review.status,
            "human_feedback": review.human_feedback,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        } if review else None,
    )


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

    # ── Conflict guards ──────────────────────────────────────────────
    # 1. Agent must be idle
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")

    # 2. Project must not have a running task
    running_in_project = (
        db.query(Task)
        .filter(Task.project_id == project_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
        .first()
    )
    if running_in_project:
        raise HTTPException(status_code=409, detail=f"项目已有任务 (#{running_in_project.id}) 正在执行，请等待完成")

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

    # Notify all clients: new task created + agent started working
    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "pending"})
    broadcast_sync("agent_update", {"id": agent.id, "status": "working"})

    # Run agent pipeline in background
    from app.services.agent_runner import run_agent_pipeline
    background_tasks.add_task(run_agent_pipeline, task.id)

    return _task_to_response(task)


# ── Global task listing (across all projects) ─────────────────────────

@global_router.get("", response_model=list[TaskResponse])
def list_all_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = (
        db.query(Task)
        .options(joinedload(Task.agent), joinedload(Task.project))
        .order_by(Task.id.desc())
        .limit(100)
        .all()
    )
    return [_task_to_response(t) for t in tasks]
