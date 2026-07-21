import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc, asc, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.pagination import paginate
from app.core.permissions import require_project_member
from app.models.models import User, Project, ProjectMember, Agent, Task, TaskStatus, AgentStatus, QualityGateRun, Review, ReviewVote, ReviewReviewer, ReviewRound, Version
from app.services import git_service as git
from app.services import quality_gate_service as quality_gates
from app.services.audit_service import record as audit_record
from app.models.models import AuditAction, AuditActorType
from agent_service.planner import plan_task, collect_project_context


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
    reviewer_agent_id: int | None = None
    security_agent_id: int | None = None
    approval_percent: int = Field(default=50, ge=1, le=100)
    # Nested-agent: a child task belongs to a parent task tree.
    parent_task_id: int | None = Field(default=None)


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    approval_percent: int = 50
    status: str
    archived: bool = False
    agent_id: int
    reviewer_agent_id: int | None = None
    security_agent_id: int | None = None
    project_id: int
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    merge_error: str = ""
    agent_name: str | None = None
    agent_role: str | None = None
    reviewer_agent_name: str | None = None
    security_agent_name: str | None = None
    project_name: str | None = None
    # Nested-agent fields
    parent_task_id: int | None = None
    plan_json: str = "[]"
    subtask_count: int = 0
    subtask_done: int = 0

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
    reviewer_agent_id: int | None = None
    security_agent_id: int | None = None
    project_id: int
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    merge_error: str = ""
    agent_name: str | None = None
    agent_role: str | None = None
    agent_model: str | None = None
    agent_runner_type: str | None = None
    reviewer_agent_name: str | None = None
    security_agent_name: str | None = None
    project_name: str | None = None
    review: dict | None = None
    quality_gate: dict | None = None

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
        reviewer_agent_id=t.reviewer_agent_id,
        security_agent_id=t.security_agent_id,
        project_id=t.project_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
        started_at=t.started_at.isoformat() if t.started_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
        merge_error=t.merge_error or "",
        agent_name=t.agent.name if t.agent else None,
        agent_role=t.agent.role if t.agent else None,
        reviewer_agent_name=t.reviewer_agent.name if t.reviewer_agent else None,
        security_agent_name=t.security_agent.name if t.security_agent else None,
        project_name=t.project.name if t.project else None,
        parent_task_id=t.parent_task_id,
        plan_json=t.plan_json or "[]",
        subtask_count=t.subtask_count or 0,
        subtask_done=t.subtask_done or 0,
    )


def _quality_gate_to_dict(run: QualityGateRun | None) -> dict | None:
    if not run:
        return None
    try:
        checks = json.loads(run.results_json or "[]")
    except (TypeError, json.JSONDecodeError):
        checks = []
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("status") == "failed":
                check["agent_actionable"] = quality_gates.is_agent_actionable_failure(check)
    return {
        "id": run.id,
        "task_id": run.task_id,
        "review_id": run.review_id,
        "attempt": run.attempt,
        "commit_hash": run.commit_hash or "",
        "status": run.status,
        "summary": run.summary or "",
        "checks": checks if isinstance(checks, list) else [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }





@router.get("")
def list_tasks(
    project_id: int,
    archived: bool = False,
    sort: str = Query(default="created_desc", description="created_desc | created_asc | status | title_asc | title_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
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
        .options(joinedload(Task.agent), joinedload(Task.reviewer_agent), joinedload(Task.security_agent), joinedload(Task.project))
    )
    # Filter by archived status — default shows active (non-archived) tasks
    q = q.filter(Task.archived == bool(archived))
    if order is not None:
        q = q.order_by(order)
    else:
        q = q.order_by(Task.id.desc())

    tasks, paging = paginate(q, page, page_size)

    # Client-side status sort — only sorts within the current page when paginated
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

    return {"items": [_task_to_response(t) for t in tasks], **paging}


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
        .options(joinedload(Task.agent), joinedload(Task.reviewer_agent), joinedload(Task.security_agent), joinedload(Task.project))
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Find associated review
    review = db.query(Review).filter(Review.task_id == task.id).order_by(Review.id.desc()).first()
    quality_gate = db.query(QualityGateRun).filter(
        QualityGateRun.task_id == task.id
    ).order_by(QualityGateRun.id.desc()).first()

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
        quality_gate=_quality_gate_to_dict(quality_gate),
    )


@router.get("/{task_id}/quality-gate")
def get_quality_gate(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(
        Task.id == task_id, Task.project_id == project_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    run = db.query(QualityGateRun).filter(
        QualityGateRun.task_id == task.id
    ).order_by(QualityGateRun.id.desc()).first()
    return _quality_gate_to_dict(run)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: int,
    req: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_task_access(project_id, user, db)

    # ── Resolve and validate agents ──────────────────────────────────

    def _resolve_agent(aid: int | None, role: str) -> Agent | None:
        """Validate that *aid* exists and has the expected *role*.
        When *aid* is None, auto-pick the first idle agent with that role.
        """
        if aid is not None:
            a = db.query(Agent).filter(Agent.id == aid).first()
            if not a:
                raise HTTPException(status_code=404, detail=f"Agent #{aid} not found")
            if a.role != role:
                raise HTTPException(
                    status_code=400,
                    detail=f"Agent「{a.name}」的角色是 {ROLE_LABELS.get(a.role, a.role)}，不能作为 {ROLE_LABELS.get(role, role)} Agent 使用",
                )
            return a
        # Auto-select the first idle agent with the target role.
        return db.query(Agent).filter(
            Agent.role == role, Agent.status == AgentStatus.IDLE,
        ).first()

    agent = _resolve_agent(req.agent_id, "code_gen")
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    reviewer_agent = _resolve_agent(req.reviewer_agent_id, "reviewer")
    security_agent = _resolve_agent(req.security_agent_id, "security")

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
        reviewer_agent_id=reviewer_agent.id if reviewer_agent else None,
        security_agent_id=security_agent.id if security_agent else None,
        project_id=project_id,
        title=req.title,
        description=req.description,
        approval_percent=req.approval_percent,
        status=TaskStatus.PENDING,
        parent_task_id=req.parent_task_id,
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


# ── Nested-agent planning (阶段 B) ──────────────────────────────────

class PlanRequest(BaseModel):
    # Optional per-step agent assignment. Length must match the number of
    # generated steps when provided; missing entries fall back to the parent
    # agent so the planning tree can run on distinct agents for parallelism.
    agents: list[int] | None = None
    auto_start: bool = False


class SubtaskBrief(BaseModel):
    id: int
    title: str
    status: str
    agent_id: int
    agent_name: str | None = None


class PlanResponse(BaseModel):
    parent: TaskResponse
    plan: list[dict]
    subtasks: list[SubtaskBrief]


@router.post("/{task_id}/plan", response_model=PlanResponse)
def plan_task_endpoint(
    project_id: int,
    task_id: int,
    req: PlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Decompose a parent task into child tasks via a planning model.

    The parent task enters PLANNING; each generated step becomes a child Task
    (sharing the parent's project). With ``auto_start`` the children are queued
    and the parent moves to SUBTASK_RUNNING. Any planning failure keeps the
    parent untouched (fail-closed for the planning step itself).
    """
    project = _check_task_access(project_id, user, db)
    require_project_member(project_id, user, db)
    parent = db.query(Task).filter(
        Task.id == task_id, Task.project_id == project_id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Task not found")
    if parent.parent_task_id is not None:
        raise HTTPException(status_code=400, detail="子任务不能再次拆解")
    if parent.status not in (TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.PLANNING):
        raise HTTPException(status_code=400, detail=f"仅待开始/失败的任务可规划，当前状态：{parent.status.value}")

    agent = db.get(Agent, parent.agent_id) if parent.agent_id else None
    if not agent:
        raise HTTPException(status_code=400, detail="父任务未绑定 Agent，无法规划")

    model_name = agent.model or "deepseek-chat"
    from app.core.config import settings
    steps = plan_task(
        f"{parent.title}\n{parent.description}".strip(),
        model_name,
        settings.DEEPSEEK_API_KEY,
        settings.DEEPSEEK_BASE_URL,
        int(agent.max_subtasks) if agent.max_subtasks else 6,
        project_context=collect_project_context(project.workspace_path),
    )
    if not steps:
        raise HTTPException(status_code=422, detail="规划模型未能生成可用子任务，请稍后重试或手动创建子任务")

    plan_payload = [
        {"id": s.id, "title": s.title, "goal": s.goal, "deps": s.deps}
        for s in steps
    ]
    parent.plan_json = json.dumps(plan_payload, ensure_ascii=False)
    parent.subtask_count = len(steps)
    parent.subtask_done = 0
    parent.status = TaskStatus.PLANNING
    db.flush()

    children: list[Task] = []
    for idx, step in enumerate(steps):
        child_agent_id = agent.id
        if req.agents and idx < len(req.agents):
            child_agent_id = req.agents[idx]
        child = Task(
            title=f"{step.title}",
            description=f"{step.goal}\n\n（来自父任务「{parent.title}」子步骤 {step.id}）",
            agent_id=child_agent_id,
            approval_percent=parent.approval_percent,
            project_id=project_id,
            status=TaskStatus.PENDING,
            parent_task_id=parent.id,
        )
        db.add(child)
        children.append(child)
    db.flush()
    for c in children:
        db.refresh(c)

    audit_record(
        action=AuditAction.TASK_CREATE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        task_id=parent.id,
        target_type="task",
        target_id=parent.id,
        intent=f"规划拆解为 {len(steps)} 个子任务",
        payload={"plan": plan_payload},
    )

    # Create the parent's single shared worktree/branch up front so every child
    # commits onto the SAME branch — that yields ONE combined change for ONE
    # aggregated review.  (Children also lazily create it if this step is skipped.)
    if not parent.worktree_path:
        ws = git.default_task_worktree_path(project.workspace_path, parent.id)
        bname = f"task/{parent.id}"
        created, werr = git.create_task_worktree(project.workspace_path, ws, bname)
        if created:
            parent.worktree_path = ws
            parent.branch_name = bname
            parent.base_commit = git.head_commit(project.workspace_path, git.get_base_branch(project.workspace_path))
            db.commit()
        # Non-fatal: the first child pipeline retries if creation failed here.

    if req.auto_start:
        db.commit()  # Persist children (and parent worktree) before queuing.
        from app.services.execution_service import enqueue_agent_run
        # Only the first child is queued; it chains the rest sequentially so the
        # children write to the shared parent branch one at a time.
        if children:
            first = children[0]
            claimed = db.query(Task).filter(
                Task.id == first.id, Task.status == TaskStatus.PENDING
            ).update(
                {Task.status: TaskStatus.RUNNING, Task.started_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
            db.commit()
            if claimed and enqueue_agent_run(first.id):
                parent.status = TaskStatus.SUBTASK_RUNNING
                db.commit()
    else:
        db.commit()
    db.refresh(parent)

    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": parent.id, "project_id": project_id, "status": parent.status.value})

    return PlanResponse(
        parent=_task_to_response(parent),
        plan=plan_payload,
        subtasks=[
            SubtaskBrief(
                id=c.id, title=c.title, status=c.status.value,
                agent_id=c.agent_id,
                agent_name=(c.agent.name if c.agent else None),
            )
            for c in children
        ],
    )


@router.get("/{task_id}/subtasks", response_model=PlanResponse)
def get_subtasks(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a parent task's planning tree and live child progress."""
    _check_task_access(project_id, user, db)
    require_project_member(project_id, user, db)
    parent = db.query(Task).filter(
        Task.id == task_id, Task.project_id == project_id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Task not found")

    children = db.query(Task).filter(Task.parent_task_id == parent.id).order_by(Task.id).all()

    terminal = {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.FAILED,
                TaskStatus.MERGE_QUEUED, TaskStatus.MERGING, TaskStatus.INTEGRATING,
                TaskStatus.MERGED, TaskStatus.MERGE_BLOCKED, TaskStatus.SUBTASK_DONE}
    done = sum(1 for c in children if c.status in terminal)
    parent.subtask_done = done
    if children and parent.status in (TaskStatus.PLANNING, TaskStatus.SUBTASK_RUNNING) and done == len(children):
        # All children reached a terminal state.  Only promote the parent to
        # REVIEWING once the pipeline has actually created the aggregated parent
        # review, so the frontend never sees a "reviewing" parent with no review
        # attached (the pipeline builds the review + gate + approval round).
        if db.query(Review).filter(Review.task_id == parent.id).first():
            parent.status = TaskStatus.REVIEWING
    db.commit()

    try:
        plan = json.loads(parent.plan_json or "[]")
    except (ValueError, TypeError):
        plan = []

    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": parent.id, "project_id": project_id, "status": parent.status.value})

    return PlanResponse(
        parent=_task_to_response(parent),
        plan=plan,
        subtasks=[
            SubtaskBrief(
                id=c.id, title=c.title, status=c.status.value,
                agent_id=c.agent_id,
                agent_name=(c.agent.name if c.agent else None),
            )
            for c in children
        ],
    )


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
    _check_task_access(project_id, user, db)
    require_project_member(project_id, user, db)
    task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"只有待开始的任务才能启动，当前状态：{task.status.value}")

    if task.parent_task_id is not None:
        # Children of a planning tree share the parent's branch and run serially.
        # Block starting a second child while another sibling is still running.
        sibling_running = db.query(Task).filter(
            Task.parent_task_id == task.parent_task_id,
            Task.status == TaskStatus.RUNNING,
        ).first()
        if sibling_running:
            raise HTTPException(
                status_code=409,
                detail=f"父任务的另一个子任务 #{sibling_running.id} 正在执行，子任务共享同一分支需串行执行，请等待其完成",
            )

    agent = db.get(Agent, task.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.WORKING and task.parent_task_id is None:
        # Top-level tasks still enforce one-agent-one-task. Child tasks in a
        # planning tree may run concurrently, so the guard is relaxed for them.
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
    """Stop a running or pending task, set status to paused."""
    _check_task_access(project_id, user, db)
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
    """Resume a paused task."""
    _check_task_access(project_id, user, db)
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
    """Archive a completed or failed task. Pending/running tasks cannot be archived."""
    _check_task_access(project_id, user, db)
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
    """Restore an archived task back to the active list."""
    _check_task_access(project_id, user, db)
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
    db.query(QualityGateRun).filter(
        QualityGateRun.task_id == task_id
    ).delete(synchronize_session=False)
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

    # Clean up Git resources (worktree + branch) if the task had executed.
    from app.models.models import Project
    from app.services import git_service as git
    proj = db.get(Project, project_id)
    if proj and proj.workspace_path:
        try:
            if task.worktree_path:
                branch_name = task.branch_name or f"task/{task_id}"
                git.cleanup_task_resources(proj.workspace_path, task.worktree_path, branch_name)
        except Exception:
            logger.warning("Git cleanup failed for deleted task %s", task_id)

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
    db.query(QualityGateRun).filter(
        QualityGateRun.task_id.in_(task_ids)
    ).delete(synchronize_session=False)
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

@global_router.get("")
def list_all_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        db.query(Task)
        .join(Project, Task.project_id == Project.id)
        .outerjoin(ProjectMember, and_(
            ProjectMember.project_id == Project.id,
            ProjectMember.user_id == user.id,
        ))
        .filter(Task.archived == False)
        .filter(or_(Project.owner_id == user.id, ProjectMember.user_id == user.id))
        .options(joinedload(Task.agent), joinedload(Task.reviewer_agent), joinedload(Task.security_agent), joinedload(Task.project))
        .order_by(Task.id.desc())
    )
    tasks, paging = paginate(q, page, page_size)
    return {"items": [_task_to_response(t) for t in tasks], **paging}


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
