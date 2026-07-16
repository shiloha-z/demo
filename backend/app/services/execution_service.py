"""Bounded local executors for agent runs and project merge queues.

The database remains the source of truth for task state.  Executors only
schedule work; on restart, queued merge tasks are re-enqueued by the app
lifespan hook.  This provides safe concurrency without allowing an arbitrary
number of HTTP requests to create simultaneous model calls.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import RLock

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus


_agent_executor = ThreadPoolExecutor(max_workers=max(1, settings.AGENT_MAX_CONCURRENCY))
_merge_executor = ThreadPoolExecutor(max_workers=max(1, settings.MERGE_MAX_CONCURRENCY))
_lock = RLock()
_active_agent_tasks: set[int] = set()
_active_merge_projects: set[int] = set()


def enqueue_agent_run(
    task_id: int,
    feedback: str = "",
    resume: bool = False,
    conflict_resolution: bool = False,
) -> bool:
    """Queue one execution per task; duplicate UI requests are harmless."""
    with _lock:
        if task_id in _active_agent_tasks:
            return False
        _active_agent_tasks.add(task_id)
    _agent_executor.submit(_run_agent, task_id, feedback, resume, conflict_resolution)
    return True


def _run_agent(task_id: int, feedback: str, resume: bool, conflict_resolution: bool) -> None:
    try:
        from app.services.agent_runner import run_agent_pipeline
        run_agent_pipeline(task_id, feedback, resume, conflict_resolution)
    finally:
        with _lock:
            _active_agent_tasks.discard(task_id)


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
