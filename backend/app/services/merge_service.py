"""Project-level serial integration, validation, and conflict hand-off."""

from datetime import datetime, timezone

from app.api.ws import broadcast_sync
from app.core.database import SessionLocal
from app.models.models import (
    Agent,
    AgentStatus,
    Project,
    QualityGateRun,
    Review,
    ReviewStatus,
    Task,
    TaskStatus,
    Version,
)
from app.services import git_service as git
from app.services.audit_service import record as audit_record
from app.models.models import AuditAction, AuditActorType
from app.core.config import settings


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
        max_attempts = max(1, int(getattr(settings, "MERGE_MAX_ATTEMPTS", 4)))
        if (task.merge_attempts or 0) >= max_attempts:
            _update_task(
                task,
                TaskStatus.MERGE_BLOCKED,
                (
                    f"合并已连续尝试 {task.merge_attempts} 次仍未成功，已停止自动重试。"
                    "请检查冲突文件或调整任务改动后再重新提交。"
                ),
            )
            db.commit()
            _broadcast(task)
            return
        review = db.query(Review).filter(
            Review.task_id == task.id,
        ).order_by(Review.id.desc()).first()
        if (
            not review
            or review.status != ReviewStatus.APPROVED
            or not (review.agent_review_summary or "").strip()
        ):
            _update_task(
                task,
                TaskStatus.MERGE_BLOCKED,
                "AI 审查报告和人工审批尚未同时满足，禁止执行合并",
            )
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
        gate_run = db.query(QualityGateRun).filter(
            QualityGateRun.review_id == review.id,
        ).order_by(QualityGateRun.id.desc()).first()
        branch_commit = git.head_commit(task.worktree_path)
        if settings.QUALITY_GATE_ENABLED and (
            not gate_run
            or gate_run.status != "passed"
            or not gate_run.commit_hash
            or gate_run.commit_hash != branch_commit
        ):
            _update_task(
                task,
                TaskStatus.MERGE_BLOCKED,
                "确定性门禁未通过，或门禁通过后的代码版本已发生变化，禁止合并",
            )
            db.commit()
            _broadcast(task)
            return
        task.status = TaskStatus.INTEGRATING
        task.merge_attempts = (task.merge_attempts or 0) + 1
        task.merge_error = ""
        db.commit()
        _broadcast(task)

        # Sync the task branch with latest master BEFORE attempting integration.
        task_wt = task.worktree_path or git.default_task_worktree_path(project.workspace_path, task.id)
        synced = True
        sync_conflicts: list[str] = []
        if task_wt and git.get_repo(task_wt):
            synced, sync_conflicts = git.sync_task_branch_with_master(task_wt, branch_name)

        if not synced and sync_conflicts:
            # Sync had conflicts — hand off to the agent for resolution directly.
            conflict_list = ", ".join(sync_conflicts)
            task.status = TaskStatus.CONFLICT_RESOLUTION
            task.merge_error = f"Merge conflict in: {conflict_list}"
            task.completed_at = None
            db.commit()
            _broadcast(task)
            git.prepare_conflict_resolution(task_wt, project.workspace_path, branch_name)
            # Enqueue the conflict-resolution agent.
            agent = db.get(Agent, task.agent_id)
            if agent:
                agent.status = AgentStatus.WORKING
            db.commit()
            if agent:
                broadcast_sync("agent_update", {"id": agent.id, "status": "working", "current_task_id": task.id})
            from app.services.execution_service import enqueue_agent_run
            feedback = (
                "主分支合并时发生冲突。请只解决以下文件中的 Git 冲突标记，保留双方意图，"
                "不要丢弃任一方的有效改动。解决后检查代码并提交，系统会重新尝试合并。\n"
                f"冲突文件：{conflict_list}"
            )
            enqueue_agent_run(task.id, feedback=feedback, conflict_resolution=True)
            return

        # Only integration touches the base workspace.  Agent worktrees have
        # their own locks and continue running independently.
        # The task branch is now synced — merge into master will be clean.
        with git.workspace_lock(project.workspace_path):
            result = git.begin_integration(project.workspace_path, branch_name)
            if result["status"] == "ready":
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

                # Audit: 对项目的影响 —— 合并完成（落库版本，记录影响范围）。
                audit_record(
                    action=AuditAction.MERGE_DONE,
                    actor_type=AuditActorType.SYSTEM,
                    project_id=project.id,
                    task_id=task.id,
                    target_type="version",
                    target_id=commit_or_error,
                    intent=f"审查通过后合并任务 #{task.id} 到主分支",
                    impact=f"版本 {commit_or_error}：任务「{task.title}」已合并至主分支",
                )

                git.cleanup_task_resources(project.workspace_path, task.worktree_path, branch_name)
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

        # Audit: 对项目的影响 —— 合并冲突，转交 Agent 自动解决。
        audit_record(
            action=AuditAction.CONFLICT_AUTO_RESOLVED,
            actor_type=AuditActorType.SYSTEM,
            project_id=project.id,
            task_id=task.id,
            target_type="task",
            target_id=task.id,
            intent=f"合并冲突，转交 Agent 自动解决（冲突文件：{conflict_list}）",
            impact=f"任务 #{task.id} 合并主分支时发生冲突：{conflict_list}",
        )
        agent = db.get(Agent, task.agent_id)
        if agent:
            agent.status = AgentStatus.WORKING
        db.commit()
        _broadcast(task)
        if agent:
            broadcast_sync("agent_update", {"id": agent.id, "status": "working", "current_task_id": task.id})

        # Push a user-facing notification so the project members see it.
        try:
            from app.services import message_service as msg
            from app.models.models import MessageCategory, MessageLevel
            msg.push(
                title=f"合并冲突 — 任务 #{task.id}「{task.title}」",
                body=(
                    f"任务合并到主分支时与另一任务的改动冲突，Agent 正在自动解决。"
                    f"冲突文件：{conflict_list}"
                ),
                category=MessageCategory.TASK,
                level=MessageLevel.WARNING,
                project_id=project.id,
                link=f"/tasks",
            )
        except Exception:
            pass

        from app.services.execution_service import enqueue_agent_run
        feedback = (
            "你的任务因合并冲突被暂停。主分支在你工作期间已由其他任务更新，"
            "导致以下文件产生 Git 冲突标记（<<<<<<< / ======= / >>>>>>>）。\n\n"
            f"冲突文件：{conflict_list}\n\n"
            "请严格按照以下步骤操作：\n"
            "1. 打开上述冲突文件，找到所有 <<<<<<<、=======、>>>>>>> 标记\n"
            "2. 理解双方的改动意图，手动合并——保留双方的有效改动，不要丢弃任何一方的代码\n"
            "3. 移除所有 Git 冲突标记（<<<<<<<、=======、>>>>>>>）\n"
            "4. 确认合并后的代码能正常运行\n"
            "5. 提交修复后的文件\n\n"
            "绝对禁止：\n"
            "- 不要重写或重新生成任何文件！只修复冲突标记！\n"
            "- 不要修改没有冲突标记的文件！\n"
            "- 不要丢弃任何一方的有效代码！\n\n"
            "完成后系统会重新发起审查和合并。"
        )
        enqueue_agent_run(task.id, feedback=feedback, conflict_resolution=True)
    finally:
        db.close()
