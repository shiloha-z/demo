from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc, asc, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_project_member
from app.models.models import User, Project, ProjectMember, Agent, Task, TaskStatus, AgentStatus, Review
from app.services import git_service as git

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
    started_at: str | None = None
    completed_at: str | None = None
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
    started_at: str | None = None
    completed_at: str | None = None
    agent_name: str | None = None
    agent_role: str | None = None
    agent_model: str | None = None
    agent_runner_type: str | None = None
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
        started_at=t.started_at.isoformat() if t.started_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
        agent_name=t.agent.name if t.agent else None,
        agent_role=t.agent.role if t.agent else None,
        project_name=t.project.name if t.project else None,
    )


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    project_id: int,
    archived: bool = False,
    sort: str = Query(default="created_desc", description="created_desc | created_asc | status | title_asc | title_desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List tasks for a project. Set ?archived=true to show only archived tasks."""
    require_project_member(project_id, user, db)
    sort_map = {
        "created_desc": desc(Task.created_at),
        "created_asc": asc(Task.created_at),
        "title_asc": asc(Task.title),
        "title_desc": desc(Task.title),
    }
    order = sort_map.get(sort)
    q = (
        db.query(Task)
        .filter(Task.project_id == project_id)
        .options(joinedload(Task.agent), joinedload(Task.project))
    )
    # Filter by archived status — default shows active (non-archived) tasks
    q = q.filter(Task.archived == bool(archived))
    if order is not None:
        q = q.order_by(order)
    else:
        q = q.order_by(Task.id.desc())

    tasks = q.all()

    # Client-side status sort (group pending/running/reviewing first, then approved/rejected/failed)
    if sort == "status":
        status_priority = {
            "running": 0, "pending": 1, "reviewing": 2,
            "failed": 3, "rejected": 4, "approved": 5, "completed": 6,
        }
        tasks.sort(key=lambda t: status_priority.get(
            t.status.value if hasattr(t.status, 'value') else str(t.status), 99
        ))

    return [_task_to_response(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_member(project_id, user, db)
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
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        agent_name=task.agent.name if task.agent else None,
        agent_role=task.agent.role if task.agent else None,
        agent_model=task.agent.model if task.agent else None,
        agent_runner_type=task.agent.runner_type if task.agent else None,
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
    require_project_member(project_id, user, db)

    # Validate agent exists (globally)
    agent = db.query(Agent).filter(Agent.id == req.agent_id, Agent.creator_id == user.id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # ── Conflict guard ───────────────────────────────────────────────
    # Agent must be idle — one agent can only run one task at a time
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")
    # Block if agent has a task currently running (covers gap when status hasn't synced)
    existing_running = (
        db.query(Task)
        .filter(Task.agent_id == req.agent_id, Task.status == TaskStatus.RUNNING)
        .first()
    )
    if existing_running:
        raise HTTPException(status_code=409,
            detail=f"Agent「{agent.name}」有任务 #${existing_running.id} 正在执行，请等待完成")
    # Also block if agent has a task awaiting review (must approve/reject first)
    existing_reviewing = (
        db.query(Task)
        .filter(Task.agent_id == req.agent_id, Task.status == TaskStatus.REVIEWING)
        .first()
    )
    if existing_reviewing:
        raise HTTPException(status_code=409,
            detail=f"Agent「{agent.name}」有任务 #${existing_reviewing.id} 待审核，请先处理审查")

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

    # Notify all clients: new task created
    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "pending"})

    return _task_to_response(task)


# ── Start task (manual trigger) ─────────────────────────────────────

@router.post("/{task_id}/start", response_model=TaskResponse)
def start_task(
    project_id: int,
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually start a pending task. Agent must be idle."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"只有待开始的任务才能启动，当前状态：{task.status.value}")

    agent = db.query(Agent).get(task.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")

    # Update agent status
    agent.status = AgentStatus.WORKING
    db.commit()

    # Run agent pipeline in background (pipeline broadcasts agent_update with full detail)
    from app.services.agent_runner import run_agent_pipeline
    background_tasks.add_task(run_agent_pipeline, task.id)

    return _task_to_response(task)


# ── Stop / Resume ────────────────────────────────────────────────────

@router.post("/{task_id}/stop", response_model=TaskResponse)
def stop_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stop a running or pending task, set status to paused."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail=f"只有等待中或执行中的任务才能暂停，当前状态：{task.status.value}")

    task.status = TaskStatus.PAUSED

    # Restore agent to idle
    agent = db.query(Agent).get(task.agent_id)
    if agent and agent.status == AgentStatus.WORKING:
        agent.status = AgentStatus.IDLE

    db.commit()

    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "paused"})
    if agent:
        broadcast_sync("agent_update", {"id": agent.id, "status": "idle"})

    return _task_to_response(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
def resume_task(
    project_id: int,
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resume a paused task."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PAUSED:
        raise HTTPException(status_code=400, detail=f"只有已暂停的任务才能继续执行，当前状态：{task.status.value}")

    agent = db.query(Agent).get(task.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")

    # Restore agent status
    agent.status = AgentStatus.WORKING
    db.commit()

    # Run agent pipeline in background — resume preserves existing task branch
    from app.services.agent_runner import run_agent_pipeline
    background_tasks.add_task(run_agent_pipeline, task.id, "", resume=True)

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
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.REVIEWING):
        raise HTTPException(status_code=400, detail="只有已结束的任务才能归档（已通过/已驳回/已完成/失败）")
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
    require_project_member(project_id, user, db)
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
    require_project_member(project_id, user, db)
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
    require_project_member(project_id, user, db)
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
        .join(Project, Task.project_id == Project.id)
        .outerjoin(ProjectMember, and_(
            ProjectMember.project_id == Project.id,
            ProjectMember.user_id == user.id,
        ))
        .filter(Task.archived == False)
        .filter(or_(Project.owner_id == user.id, ProjectMember.user_id == user.id))
        .options(joinedload(Task.agent), joinedload(Task.project))
        .order_by(Task.id.desc())
        .limit(100)
        .all()
    )
    return [_task_to_response(t) for t in tasks]


# ── Task workspace (browse task branch files) ─────────────────────────

@router.get("/{task_id}/files")
def task_file_tree(
    project_id: int,
    task_id: int,
    path: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List files from the task's working branch (task/{task_id})."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = db.query(Project).get(project_id)
    if not project or not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    try:
        nodes = git.list_files(project.workspace_path, path, ref=f"task/{task_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"files": nodes}


@router.get("/{task_id}/file")
def task_read_file(
    project_id: int,
    task_id: int,
    path: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read a file from the task's working branch (task/{task_id})."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = db.query(Project).get(project_id)
    if not project or not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    try:
        content = git.read_file(project.workspace_path, path, ref=f"task/{task_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}
