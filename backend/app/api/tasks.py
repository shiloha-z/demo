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
    archived: bool = False
    agent_id: int
    project_id: int
    created_at: str | None = None
    agent_name: str | None = None
    agent_role: str | None = None
    project_name: str | None = None

    class Config:
        from_attributes = True


class BatchDeleteRequest(BaseModel):
    task_ids: list[int] = Field(..., min_length=1)


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

ROLE_LABELS: dict[str, str] = {
    "code_gen": "代码生成",
    "reviewer": "审查",
    "security": "安全",
}


def _task_to_response(t: Task) -> TaskResponse:
    return TaskResponse(
        id=t.id,
        title=t.title,
        description=t.description,
        status=t.status.value if hasattr(t.status, 'value') else t.status,
        archived=bool(t.archived),
        agent_id=t.agent_id,
        project_id=t.project_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
        agent_name=t.agent.name if t.agent else None,
        agent_role=t.agent.role if t.agent else None,
        project_name=t.project.name if t.project else None,
    )


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    project_id: int,
    archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List tasks for a project. Set ?archived=true to show only archived tasks."""
    q = (
        db.query(Task)
        .filter(Task.project_id == project_id)
        .options(joinedload(Task.agent), joinedload(Task.project))
    )
    # Filter by archived status — default shows active (non-archived) tasks
    q = q.filter(Task.archived == bool(archived))
    tasks = q.order_by(Task.id.desc()).all()
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

    # ── Conflict guard ───────────────────────────────────────────────
    # Agent must be idle (one agent can only run one task at a time)
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")

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


# ── Archive / Unarchive / Delete ──────────────────────────────────────

@router.post("/{task_id}/archive")
def archive_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Archive a completed or failed task. Pending/running tasks cannot be archived."""
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="只有已完成或失败的任务才能归档")
    if task.archived:
        raise HTTPException(status_code=400, detail="任务已归档")
    task.archived = True
    db.commit()
    return {"message": "已归档"}


@router.post("/{task_id}/unarchive")
def unarchive_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore an archived task back to the active list."""
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.archived:
        raise HTTPException(status_code=400, detail="任务未归档")
    task.archived = False
    db.commit()
    return {"message": "已取消归档"}


@router.delete("/{task_id}")
def delete_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Permanently delete a task. Only archived tasks can be deleted."""
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.archived:
        raise HTTPException(status_code=400, detail="请先归档任务再删除")
    db.delete(task)
    db.commit()
    return {"message": "已删除"}


@router.post("/batch-delete")
def batch_delete_tasks(
    project_id: int,
    req: BatchDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Batch delete archived tasks."""
    tasks = db.query(Task).filter(
        Task.id.in_(req.task_ids),
        Task.project_id == project_id,
        Task.archived == True,
    ).all()
    if not tasks:
        raise HTTPException(status_code=404, detail="No matching archived tasks found")
    deleted_count = 0
    for t in tasks:
        db.delete(t)
        deleted_count += 1
    db.commit()
    return {"message": f"已删除 {deleted_count} 个任务", "count": deleted_count}


# ── Global task listing (across all projects) ─────────────────────────

@global_router.get("", response_model=list[TaskResponse])
def list_all_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = (
        db.query(Task)
        .filter(Task.archived == False)
        .options(joinedload(Task.agent), joinedload(Task.project))
        .order_by(Task.id.desc())
        .limit(100)
        .all()
    )
    return [_task_to_response(t) for t in tasks]
