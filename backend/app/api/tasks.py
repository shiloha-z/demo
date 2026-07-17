from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc, asc, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_project_member
from app.models.models import User, Project, ProjectMember, Agent, Task, TaskStatus, AgentStatus, Review, ReviewVote, ReviewReviewer, ReviewRound, Version
from app.services import git_service as git
from app.services.audit_service import record as audit_record
from app.models.models import AuditAction, AuditActorType


router = APIRouter(prefix="/api/projects/{project_id}/tasks", tags=["Tasks"])

# Separate router for global task listing (no project_id in path)
global_router = APIRouter(prefix="/api/tasks", tags=["Tasks Global"])


# ── Permission helper ─────────────────────────────────────────────────

def _check_task_access(project_id: int, user: User, db: Session) -> Project:
    """Verify user is a member of the project. Raises 404/403."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == user.id:
        return project
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="只有项目成员才能进行此操作")
    return project


# ── Schemas ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    agent_id: int
    approval_percent: int = Field(default=50, ge=1, le=100)


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    approval_percent: int = 50
    status: str
    archived: bool = False
    agent_id: int
    project_id: int
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    merge_error: str = ""
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
    approval_percent: int = 50
    status: str
    agent_id: int
    project_id: int
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    merge_error: str = ""
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
        approval_percent=t.approval_percent or 50,
        status=t.status.value if hasattr(t.status, 'value') else t.status,
        archived=bool(t.archived),
        agent_id=t.agent_id,
        project_id=t.project_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
        started_at=t.started_at.isoformat() if t.started_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
        merge_error=t.merge_error or "",
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
    _check_task_access(project_id, user, db)
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
            "running": 0, "conflict_resolution": 1, "integrating": 2,
            "merge_queued": 3, "reviewing": 4, "pending": 5,
            "merge_blocked": 6, "failed": 7, "rejected": 8,
            "approved": 9, "completed": 10,
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
    _check_task_access(project_id, user, db)
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
        approval_percent=task.approval_percent or 50,
        status=task.status.value if hasattr(task.status, 'value') else task.status,
        agent_id=task.agent_id,
        project_id=task.project_id,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        merge_error=task.merge_error or "",
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
    _check_task_access(project_id, user, db)

    # Agents are shared globally; the project membership check above controls
    # who may assign work in this project.
    agent = db.query(Agent).filter(Agent.id == req.agent_id).first()
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
        approval_percent=req.approval_percent,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Notify all clients: new task created
    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "pending"})

    # Audit: 人为创建任务（记录指令意图）。
    audit_record(
        action=AuditAction.TASK_CREATE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
        intent=req.description,
        payload={"title": task.title, "agent_id": req.agent_id, "approval_percent": req.approval_percent},
    )

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
    _check_task_access(project_id, user, db)
    """Manually start a pending task. Agent must be idle."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"只有待开始的任务才能启动，当前状态：{task.status.value}")

    agent = db.get(Agent, task.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.WORKING:
        active_task = db.query(Task).filter(
            Task.agent_id == agent.id,
            Task.status == TaskStatus.RUNNING,
        ).first()
        if active_task:
            raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")
        # Recover from an interrupted request that set the agent to WORKING
        # before the background runner was successfully queued.
        agent.status = AgentStatus.IDLE
        db.flush()

    # Claim the task and agent conditionally in one transaction. Concurrent
    # start requests can no longer both pass the read-before-write checks.
    started_at = datetime.now(timezone.utc)
    claimed_task = db.query(Task).filter(
        Task.id == task.id,
        Task.status == TaskStatus.PENDING,
    ).update({
        Task.status: TaskStatus.RUNNING,
        Task.started_at: started_at,
    }, synchronize_session=False)
    claimed_agent = db.query(Agent).filter(
        Agent.id == agent.id,
        Agent.status != AgentStatus.WORKING,
    ).update({Agent.status: AgentStatus.WORKING}, synchronize_session=False)
    if not claimed_task or not claimed_agent:
        db.rollback()
        raise HTTPException(status_code=409, detail="任务或 Agent 已被其他请求启动")
    db.commit()
    db.refresh(task)
    db.refresh(agent)

    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {
        "id": task.id, "project_id": project_id, "status": "running",
        "started_at": task.started_at.isoformat(),
    })
    broadcast_sync("agent_update", {
        "id": agent.id, "status": "working", "current_task_id": task.id,
    })

    # Audit: 人让 AI 干的事 —— 启动任务即派发执行。
    audit_record(
        action=AuditAction.TASK_START,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
        intent=task.description,
        payload={"agent_id": agent.id, "agent_name": agent.name},
    )

    # A bounded executor queues independent worktrees; requests never create
    # unbounded concurrent model calls.
    from app.services.execution_service import enqueue_agent_run
    if not enqueue_agent_run(task.id):
        task.status = TaskStatus.PENDING
        task.started_at = None
        agent.status = AgentStatus.IDLE
        db.commit()
        broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "pending"})
        broadcast_sync("agent_update", {"id": agent.id, "status": "idle"})
        raise HTTPException(status_code=409, detail="任务已在执行或执行器正在关闭，请稍后重试")

    return _task_to_response(task)


# ── Stop / Resume ────────────────────────────────────────────────────

@router.post("/{task_id}/stop", response_model=TaskResponse)
def stop_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_task_access(project_id, user, db)
    """Stop a running or pending task, set status to paused."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail=f"只有等待中或执行中的任务才能暂停，当前状态：{task.status.value}")

    task.status = TaskStatus.PAUSED

    # Running tasks use cooperative (soft) pause. Keep the Agent busy until
    # the current runner call returns, otherwise another task could start with
    # the same Agent while the first one is still consuming resources.
    from app.services.execution_service import is_agent_run_active
    agent = db.get(Agent, task.agent_id)
    run_active = is_agent_run_active(task.id)
    other_active = db.query(Task.id).filter(
        Task.agent_id == task.agent_id,
        Task.id != task.id,
        Task.status.in_([TaskStatus.RUNNING, TaskStatus.CONFLICT_RESOLUTION]),
    ).first()
    if agent and not run_active and not other_active and agent.status == AgentStatus.WORKING:
        agent.status = AgentStatus.IDLE

    db.commit()

    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "paused"})
    if agent and not run_active and not other_active:
        broadcast_sync("agent_update", {"id": agent.id, "status": "idle"})

    audit_record(
        action=AuditAction.TASK_STOP,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
    )

    return _task_to_response(task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
def resume_task(
    project_id: int,
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_task_access(project_id, user, db)
    """Resume a paused task."""
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PAUSED:
        raise HTTPException(status_code=400, detail=f"只有已暂停的任务才能继续执行，当前状态：{task.status.value}")

    from app.services.execution_service import enqueue_agent_run, is_agent_run_active
    if is_agent_run_active(task.id):
        raise HTTPException(status_code=409, detail="当前执行仍在结束中，请稍后再恢复")

    agent = db.get(Agent, task.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.WORKING:
        raise HTTPException(status_code=409, detail=f"Agent「{agent.name}」正在执行任务，请等待完成")

    # Claim both rows conditionally. Two simultaneous resume requests cannot
    # both transition the same paused task back to running.
    started_at = datetime.now(timezone.utc)
    claimed_task = db.query(Task).filter(
        Task.id == task.id,
        Task.status == TaskStatus.PAUSED,
    ).update({
        Task.status: TaskStatus.RUNNING,
        Task.started_at: started_at,
    }, synchronize_session=False)
    claimed_agent = db.query(Agent).filter(
        Agent.id == agent.id,
        Agent.status != AgentStatus.WORKING,
    ).update({Agent.status: AgentStatus.WORKING}, synchronize_session=False)
    if not claimed_task or not claimed_agent:
        db.rollback()
        raise HTTPException(status_code=409, detail="任务或 Agent 已被其他请求恢复")
    db.commit()
    db.refresh(task)
    db.refresh(agent)

    # Resume in the task's existing isolated worktree.
    if not enqueue_agent_run(task.id, resume=True):
        task.status = TaskStatus.PAUSED
        agent.status = AgentStatus.IDLE
        db.commit()
        raise HTTPException(status_code=409, detail="任务恢复入队失败，请稍后重试")

    audit_record(
        action=AuditAction.TASK_RESUME,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
    )

    return _task_to_response(task)


# ── Archive / Unarchive / Delete ──────────────────────────────────────

@router.post("/{task_id}/archive")
def archive_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_task_access(project_id, user, db)
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

    audit_record(
        action=AuditAction.TASK_ARCHIVE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
    )
    return {"message": "已归档"}


@router.post("/{task_id}/unarchive")
def unarchive_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_task_access(project_id, user, db)
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
    _check_task_access(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.archived:
        raise HTTPException(status_code=400, detail="请先归档任务再删除")

    # Clean up review dependents first
    review_ids = [
        row[0] for row in
        db.query(Review.id).filter(Review.task_id == task_id).all()
    ]
    if review_ids:
        db.query(ReviewVote).filter(ReviewVote.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(ReviewReviewer).filter(ReviewReviewer.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(ReviewRound).filter(ReviewRound.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(Version).filter(Version.review_id.in_(review_ids)).update(
            {Version.review_id: None}, synchronize_session=False
        )
        db.query(Review).filter(Review.id.in_(review_ids)).delete(synchronize_session=False)

    db.delete(task)
    db.commit()

    audit_record(
        action=AuditAction.TASK_DELETE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=task.id,
        target_type="task",
        target_id=task.id,
    )
    return {"message": "已删除"}


@router.post("/batch-delete")
def batch_delete_tasks(
    project_id: int,
    req: BatchDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Batch delete archived tasks."""
    _check_task_access(project_id, user, db)
    tasks = db.query(Task).filter(
        Task.id.in_(req.task_ids),
        Task.project_id == project_id,
        Task.archived == True,
    ).all()
    if not tasks:
        raise HTTPException(status_code=404, detail="No matching archived tasks found")

    task_ids = [t.id for t in tasks]
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

    deleted_count = 0
    for t in tasks:
        db.delete(t)
        deleted_count += 1
    db.commit()

    audit_record(
        action=AuditAction.TASK_DELETE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="task_bulk",
        target_id=",".join(str(i) for i in task_ids),
        payload={"deleted": task_ids},
    )
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
    project = db.get(Project, project_id)
    if not project or not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    branch_name = task.branch_name or f"task/{task_id}"
    task_workspace = task.worktree_path if task.worktree_path and git.get_repo(task.worktree_path) else ""
    try:
        # Prefer the isolated task worktree so the panel also shows files that
        # have been written but not committed yet.
        workspace = task_workspace or project.workspace_path
        nodes = git.list_files(workspace, path) if task_workspace else git.list_files_snapshot(
            project.workspace_path, branch_name, path
        )
        changed_paths = git.changed_files_vs_base(workspace, "" if task_workspace else branch_name)

        def mark_changed(items: list[dict]) -> bool:
            any_changed = False
            for item in items:
                child_changed = mark_changed(item.get("children") or [])
                item_path = item.get("path", "")
                own_changed = item_path in changed_paths
                item["modified"] = own_changed or child_changed
                any_changed = any_changed or item["modified"]
            return any_changed

        mark_changed(nodes)
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
    project = db.get(Project, project_id)
    if not project or not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    branch_name = task.branch_name or f"task/{task_id}"
    task_workspace = task.worktree_path if task.worktree_path and git.get_repo(task.worktree_path) else ""
    try:
        content = git.read_file(task_workspace, path) if task_workspace else git.read_file_snapshot(
            project.workspace_path, branch_name, path
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}
