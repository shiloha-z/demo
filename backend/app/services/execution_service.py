"""Bounded local executors for agent runs and project merge queues.

The database remains the source of truth for task state.  Executors only
schedule work; on restart, queued merge tasks are re-enqueued by the app
lifespan hook.  This provides safe concurrency without allowing an arbitrary
number of HTTP requests to create simultaneous model calls.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, RLock

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Agent, AgentStatus, Task, TaskStatus
import logging

logger = logging.getLogger(__name__)



_agent_executor = ThreadPoolExecutor(max_workers=max(1, settings.AGENT_MAX_CONCURRENCY))
_merge_executor = ThreadPoolExecutor(max_workers=max(1, settings.MERGE_MAX_CONCURRENCY))
_lock = RLock()
_active_agent_tasks: set[int] = set()
_pending_agent_runs: dict[int, tuple[str, bool, bool]] = {}
_active_merge_projects: set[int] = set()
# Child tasks of a planning tree share the parent's single worktree branch, so
# only ONE child of the same parent may write to it at a time. This lock
# serializes children of a given parent (different parents may still run in
# parallel). Top-level tasks are unaffected.
_parent_run_locks: dict[int, RLock] = {}

# Child tasks of a planning tree may run concurrently across *different* parents;
# this bounds their total in-flight count to the agent pool capacity so a large
# plan can never exhaust the executor (top-level tasks are unaffected and still
# bounded by the pool).
_subtask_semaphore = BoundedSemaphore(max(1, settings.AGENT_MAX_CONCURRENCY))


def _parent_lock(parent_id: int) -> RLock:
    with _lock:
        return _parent_run_locks.setdefault(parent_id, RLock())


def enqueue_agent_run(
    task_id: int,
    feedback: str = "",
    resume: bool = False,
    conflict_resolution: bool = False,
    queue_if_active: bool = False,
) -> bool:
    """Queue one execution per task.

    A review rejection is a deliberate follow-up run, not a duplicate click.
    With ``queue_if_active`` it is retained until the finishing pipeline has
    released the task, closing the short race between its final WebSocket
    update and executor cleanup.
    """
    with _lock:
        if task_id in _active_agent_tasks:
            if queue_if_active:
                _pending_agent_runs[task_id] = (feedback, resume, conflict_resolution)
                return True
            return False
        _active_agent_tasks.add(task_id)
    try:
        _agent_executor.submit(_run_agent, task_id, feedback, resume, conflict_resolution)
    except RuntimeError:
        # The executor may be shutting down while a request is being handled.
        # Do not leave a phantom active task behind in that case.
        with _lock:
            _active_agent_tasks.discard(task_id)
        return False
    # Audit: 人让 AI 干的事 —— 任务进入执行队列（记录派发意图）。
    try:
        from app.services.audit_service import record as audit_record
        from app.models.models import AuditAction, AuditActorType, Task
        adb = SessionLocal()
        try:
            atask = adb.get(Task, task_id)
            if atask:
                audit_record(
                    action=AuditAction.AGENT_DISPATCH,
                    actor_type=AuditActorType.SYSTEM,
                    project_id=atask.project_id,
                    task_id=task_id,
                    target_type="task",
                    target_id=task_id,
                    intent=feedback or atask.description,
                    payload={"resume": resume, "conflict_resolution": conflict_resolution},
                )
        finally:
            adb.close()
    except Exception as audit_err:
        logger.warning("Failed to record agent-dispatch audit entry", exc_info=audit_err)
    return True


def is_agent_run_active(task_id: int) -> bool:
    """Return whether the in-process executor still owns this task."""
    with _lock:
        return task_id in _active_agent_tasks


def _release_paused_agent(task_id: int) -> None:
    """Mark the agent idle only after a soft-paused execution has returned."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task or task.status != TaskStatus.PAUSED:
            return
        agent = db.get(Agent, task.agent_id)
        other_active = db.query(Task.id).filter(
            Task.agent_id == task.agent_id,
            Task.id != task.id,
            Task.status.in_([TaskStatus.RUNNING, TaskStatus.CONFLICT_RESOLUTION]),
        ).first()
        if agent and not other_active and agent.status == AgentStatus.WORKING:
            agent.status = AgentStatus.IDLE
            db.commit()
            try:
                from app.api.ws import broadcast_sync
                broadcast_sync("agent_update", {"id": agent.id, "status": "idle"})
            except Exception as bcast_err:
                logger.warning("Failed to broadcast agent idle update", exc_info=bcast_err)
    finally:
        db.close()


def _run_agent(task_id: int, feedback: str, resume: bool, conflict_resolution: bool) -> None:
    pending: tuple[str, bool, bool] | None = None
    holds_subtask_slot = False
    holds_parent_lock = False
    plock = None
    try:
        # Child tasks of a planning tree consume a bounded concurrency slot so a
        # large plan cannot starve the executor. Top-level tasks run normally.
        # In addition, children of the SAME parent are serialized so they never
        # write to the shared parent branch concurrently.
        db = SessionLocal()
        try:
            t = db.get(Task, task_id)
            if t and t.parent_task_id is not None:
                _subtask_semaphore.acquire()
                holds_subtask_slot = True
                plock = _parent_lock(t.parent_task_id)
                plock.acquire()
                holds_parent_lock = True
        finally:
            db.close()
        from app.services.agent_runner import run_agent_pipeline
        run_agent_pipeline(task_id, feedback, resume, conflict_resolution)
    finally:
        if holds_parent_lock and plock is not None:
            try:
                plock.release()
            except ValueError:
                pass
        if holds_subtask_slot:
            try:
                _subtask_semaphore.release()
            except ValueError:
                pass
        # Keep the task registered as active until its agent state has been
        # reconciled. A resume request during this window must wait instead
        # of queueing a duplicate run.
        try:
            _release_paused_agent(task_id)
        finally:
            with _lock:
                _active_agent_tasks.discard(task_id)
                pending = _pending_agent_runs.pop(task_id, None)
    if pending:
        enqueue_agent_run(task_id, *pending)


def enqueue_merge(task_id: int) -> bool:
    """Start a single draining worker for this project if needed."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return False
        project_id = task.project_id
    finally:
        db.close()
    with _lock:
        if project_id in _active_merge_projects:
            return False
        _active_merge_projects.add(project_id)
    _merge_executor.submit(_drain_project_merges, project_id)
    return True


def _drain_project_merges(project_id: int) -> None:
    try:
        while True:
            db = SessionLocal()
            try:
                task = (
                    db.query(Task)
                    .filter(Task.project_id == project_id, Task.status == TaskStatus.MERGE_QUEUED)
                    .order_by(Task.merge_queued_at.asc(), Task.id.asc())
                    .first()
                )
                task_id = task.id if task else None
            finally:
                db.close()
            if task_id is None:
                return
            from app.services.merge_service import integrate_task
            integrate_task(task_id)
    finally:
        with _lock:
            _active_merge_projects.discard(project_id)


def recover_merge_queue() -> None:
    """Requeue persisted merge work after an application restart."""
    db = SessionLocal()
    try:
        interrupted = db.query(Task).filter(Task.status == TaskStatus.INTEGRATING).all()
        for task in interrupted:
            task.status = TaskStatus.MERGE_QUEUED
        db.commit()
        task_ids = [row[0] for row in db.query(Task.id).filter(
            Task.status == TaskStatus.MERGE_QUEUED
        ).all()]
    finally:
        db.close()
    for task_id in task_ids:
        enqueue_merge(task_id)


def recover_interrupted_agent_runs() -> int:
    """Make process-local work resumable after an unclean restart.

    Agent/model calls run in this process and cannot survive a restart. Leaving
    their rows in a running state permanently blocks normal resume operations
    and misreports Agent capacity. Persist them as PAUSED instead; the existing
    resume endpoint continues from the task worktree.
    """
    volatile_statuses = (
        TaskStatus.RUNNING,
        TaskStatus.CONFLICT_RESOLUTION,
        TaskStatus.PLANNING,
        TaskStatus.SUBTASK_RUNNING,
    )
    db = SessionLocal()
    try:
        recovered = (
            db.query(Task)
            .filter(Task.status.in_(volatile_statuses))
            .update({Task.status: TaskStatus.PAUSED}, synchronize_session=False)
        )
        # No executor thread survives process startup, so a persisted WORKING
        # Agent is stale even when the task row was already repaired manually.
        db.query(Agent).filter(Agent.status == AgentStatus.WORKING).update(
            {Agent.status: AgentStatus.IDLE},
            synchronize_session=False,
        )
        db.commit()
        if recovered:
            logger.warning("Recovered %s interrupted agent task(s) as paused", recovered)
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
