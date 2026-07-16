"""Project-level serial integration, validation, and conflict hand-off."""

from datetime import datetime, timezone

from app.api.ws import broadcast_sync
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Agent, AgentStatus, Project, Review, ReviewStatus, Task, TaskStatus, Version
from app.services import git_service as git


def _update_task(task: Task, status: TaskStatus, error: str = "") -> None:
    task.status = status
    task.merge_error = error


def _broadcast(task: Task) -> None:
    broadcast_sync("task_update", {
        "id": task.id,
        "project_id": task.project_id,
        "status": task.status.value,
        "merge_error": task.merge_error,
    })


def integrate_task(task_id: int) -> None:
    """Integrate one already-approved task while holding its project lock."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task or task.status != TaskStatus.MERGE_QUEUED:
            return
        project = db.get(Project, task.project_id)
        if not project or not project.workspace_path:
            _update_task(task, TaskStatus.MERGE_BLOCKED, "Project workspace not initialized")
            db.commit()
            _broadcast(task)
            return
        branch_name = task.branch_name or f"task/{task.id}"
        if not task.worktree_path:
            worktree_path = git.default_task_worktree_path(project.workspace_path, task.id)
            created, error = git.create_task_worktree(project.workspace_path, worktree_path, branch_name)
            if not created:
                _update_task(task, TaskStatus.MERGE_BLOCKED, f"Could not prepare task worktree: {error}")
                db.commit()
                _broadcast(task)
                return
            task.worktree_path = worktree_path
            task.branch_name = branch_name
            db.commit()
        task.status = TaskStatus.INTEGRATING
        task.merge_attempts = (task.merge_attempts or 0) + 1
        task.merge_error = ""
        db.commit()
        _broadcast(task)

        # Only integration touches the base workspace.  Agent worktrees have
        # their own locks and continue running independently.
        with git.workspace_lock(project.workspace_path):
            result = git.begin_integration(project.workspace_path, branch_name)
            if result["status"] == "ready":
                ok, check_output = git.run_integration_checks(
                    project.workspace_path,
                    settings.MERGE_TEST_COMMAND,
                    settings.MERGE_TEST_TIMEOUT_SECONDS,
                )
                if not ok:
                    git.abort_integration(project.workspace_path)
                    _update_task(task, TaskStatus.MERGE_BLOCKED, check_output)
                    db.commit()
                    _broadcast(task)
                    return
                merged, commit_or_error = git.finish_integration(
                    project.workspace_path,
                    f"Merge task #{task.id}: {task.title}",
                )
                if not merged:
                    git.abort_integration(project.workspace_path)
                    _update_task(task, TaskStatus.MERGE_BLOCKED, commit_or_error)
                    db.commit()
                    _broadcast(task)
                    return

                review = db.query(Review).filter(
                    Review.task_id == task.id, Review.status == ReviewStatus.APPROVED
                ).order_by(Review.id.desc()).first()
                db.add(Version(
                    project_id=project.id,
                    commit_hash=commit_or_error,
                    commit_message=f"Task #{task.id} merged after review",
                    review_id=review.id if review else None,
                ))
                task.status = TaskStatus.APPROVED
                task.completed_at = datetime.now(timezone.utc)
                task.merge_error = ""
                db.commit()

                git.remove_task_worktree(project.workspace_path, task.worktree_path)
                git.delete_branch(project.workspace_path, branch_name)
                _broadcast(task)
                broadcast_sync("version_update", {"project_id": project.id})
                broadcast_sync("file_change", {"project_id": project.id})
                return

            if result["status"] != "conflict":
                _update_task(task, TaskStatus.MERGE_BLOCKED, result.get("error", "Merge failed"))
                db.commit()
                _broadcast(task)
                return

        # Leave conflict markers in the task worktree for the resolver Agent.
        # This occurs outside the base lock: other projects and other agent
        # worktrees remain unaffected.
        prepared, files, error = git.prepare_conflict_resolution(
            task.worktree_path,
            project.workspace_path,
            branch_name,
        )
        if not prepared:
            _update_task(task, TaskStatus.MERGE_BLOCKED, error or "Could not prepare conflict resolution")
            db.commit()
            _broadcast(task)
            return
        if not files:
            # Main advanced while waiting but its changes merge cleanly into
            # the task branch; queue one fresh integration attempt.
            task.status = TaskStatus.MERGE_QUEUED
            db.commit()
            _broadcast(task)
            return

        conflict_list = ", ".join(files)
        task.status = TaskStatus.CONFLICT_RESOLUTION
        task.merge_error = f"Merge conflict in: {conflict_list}"
        task.completed_at = None
        agent = db.get(Agent, task.agent_id)
        if agent:
            agent.status = AgentStatus.WORKING
        db.commit()
        _broadcast(task)
        if agent:
            broadcast_sync("agent_update", {"id": agent.id, "status": "working", "current_task_id": task.id})

        from app.services.execution_service import enqueue_agent_run
        feedback = (
            "主分支合并时发生冲突。请只解决以下文件中的 Git 冲突标记，保留双方意图，"
            "不要丢弃任一方的有效改动。解决后检查代码并提交，系统会重新发起人工投票。\n"
            f"冲突文件：{conflict_list}"
        )
        enqueue_agent_run(task.id, feedback=feedback, conflict_resolution=True)
    finally:
        db.close()
