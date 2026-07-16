"""Agent pipeline runner — bridges FastAPI ↔ Agent Runners.

Runs in a background thread via FastAPI BackgroundTasks to avoid blocking the event loop.
Integrates with the ChromaDB 4-layer memory system (task / agent / project / global).
Pushes real-time progress via WebSocket `task_progress` and `pipeline_stage` events.

Supports multiple runner backends via agent.runner_type:
  - crewai:     4-agent CrewAI sequential pipeline
  - claude_code: Anthropic Claude Agent SDK
  - opencode:    OpenCode CLI
"""

import logging
import time
import math
from datetime import datetime, timezone
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus, Agent, AgentStatus, Review, ReviewRound, ReviewReviewer, ReviewVote, Project, ProjectMember
from app.services import git_service as git

# Lazy import — memory_service may fail if chromadb not installed
try:
    from app.services import memory_service as mem
except ImportError:
    mem = None

logger = logging.getLogger(__name__)

# ── Stage definitions (shared across runners) ───────────────────────────

STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",  "desc": "正在生成代码..."},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",   "desc": "正在检查代码质量..."},
    {"key": "security",   "label": "安全审查员", "icon": "shield","desc": "正在扫描安全漏洞..."},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",  "desc": "正在汇总审查报告..."},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _progress(task_id: int, project_id: int, message: str, step: str = ""):
    """Push a progress update via WebSocket.

    Progress logs are streamed through WebSocket only (not persisted to the
    task-memory collection) to avoid unbounded growth of per-task memory.
    Failure context is recorded separately via `_record_task_error`.
    """
    from app.api.ws import broadcast_sync

    payload = {
        "task_id": task_id,
        "project_id": project_id,
        "message": message,
        "step": step,
        "timestamp": _now_iso(),
    }
    broadcast_sync("task_progress", payload)


def _pipeline_stage(task_id: int, project_id: int, stage_key: str, status: str):
    """Push a pipeline stage update (running / done / error)."""
    from app.api.ws import broadcast_sync

    stage_info = next((s for s in STAGES if s["key"] == stage_key), None)
    broadcast_sync("pipeline_stage", {
        "task_id": task_id,
        "project_id": project_id,
        "stage": stage_key,
        "status": status,
        "label": stage_info["label"] if stage_info else stage_key,
        "icon": stage_info["icon"] if stage_info else "circle",
        "timestamp": _now_iso(),
    })


# ── Runner callbacks ────────────────────────────────────────────────────

def _make_progress_cb(task_id: int, project_id: int):
    """Create a progress callback wired to WebSocket + memory."""
    return lambda msg, step: _progress(task_id, project_id, msg, step)


def _make_stage_cb(task_id: int, project_id: int):
    """Create a stage callback wired to WebSocket pipeline_stage events."""
    return lambda stage_key, status: _pipeline_stage(task_id, project_id, stage_key, status)


# ── Main entry point ────────────────────────────────────────────────────

def run_agent_pipeline(
    task_id: int,
    feedback: str = "",
    resume: bool = False,
    conflict_resolution: bool = False,
):
    """Run an Agent in an isolated task worktree.

    Different task worktrees have independent locks, so model runs can be
    concurrent.  The base project workspace is locked only during merging.
    """
    _run_agent_pipeline(task_id, feedback, resume, conflict_resolution)


def _run_agent_pipeline(
    task_id: int,
    feedback: str = "",
    resume: bool = False,
    conflict_resolution: bool = False,
):
    """Execute the full agent pipeline for a given task.

    Dispatches to the correct runner based on agent.runner_type.
    Called by FastAPI's BackgroundTasks — runs in a thread pool.

    If `feedback` is provided, the pipeline runs in "revision" mode:
    - Reuses the existing task branch (does not create a new one from master)
    - Prepends the human feedback to the task description so the agent can address it

    If `resume` is True, the pipeline resumes from the existing task branch
    without recreating it (preserves partial work from paused state).
    """
    from app.api.ws import broadcast_sync
    from agent_service.runners.factory import get_runner

    db = SessionLocal()
    task = None
    try:
        task = db.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        project_id = task.project_id

        # Update status → running
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        broadcast_sync("task_update", {
            "id": task.id, "project_id": project_id, "status": "running",
            "started_at": task.started_at.isoformat(),
        })

        _progress(task_id, project_id, "🚀 任务开始执行", "start")
        is_revision = bool(feedback)

        _progress(task_id, project_id, f"📋 任务目标：{task.title}", "goal")
        if feedback:
            _progress(task_id, project_id, f"💬 人工反馈：{feedback[:200]}", "feedback")
        if task.description:
            _progress(task_id, project_id, f"📝 任务描述：{task.description}", "desc")

        project = db.get(Project, project_id)
        if not project or not project.workspace_path:
            _fail_task(db, task, "Project workspace not found")
            return

        # Get the agent
        agent = db.get(Agent, task.agent_id)
        model_name = agent.model if agent and agent.model else "deepseek-chat"
        agent_name = agent.name if agent else "Unknown"
        runner_type = agent.runner_type if agent and agent.runner_type else "crewai"

        if agent:
            agent.status = AgentStatus.WORKING
            db.commit()
            broadcast_sync("agent_update", {
                "id": agent.id, "status": "working",
                "current_task_id": task_id, "current_task_title": task.title,
            })

        # ── Step 1: Prepare workspace ──────────────────────────────
        _progress(task_id, project_id, "📂 正在准备项目工作空间...", "prepare")
        workspace = task.worktree_path or git.default_task_worktree_path(project.workspace_path, task.id)

        # ── Step 2: Create or reuse task branch ────────────────────
        branch_name = task.branch_name or f"task/{task.id}"
        if conflict_resolution and not git.get_repo(workspace):
            _fail_task(db, task, "Conflict worktree not found")
            return
        if not conflict_resolution and not task.worktree_path:
            created, error = git.create_task_worktree(project.workspace_path, workspace, branch_name)
            if not created:
                _fail_task(db, task, f"Could not create task worktree: {error}")
                return
            task.worktree_path = workspace
            task.branch_name = branch_name
            task.base_commit = git.head_commit(project.workspace_path, git.get_base_branch(project.workspace_path))
            db.commit()
        if not conflict_resolution:
            _progress(task_id, project_id, f"🌿 切换到已有工作分支：{branch_name}", "branch")
            git.switch_branch(workspace, branch_name)
        else:
            _progress(task_id, project_id, f"🌿 创建 Git 工作分支：{branch_name}", "branch")
            pass

        # ── Step 3: Get runner and execute ─────────────────────────
        _progress(task_id, project_id, f"🤖 启动 Agent「{agent_name}」", "agent_start")
        _progress(task_id, project_id, f"🧠 使用模型：{model_name}", "model")
        _progress(task_id, project_id, f"🔌 执行引擎：{runner_type}", "runner_type")

        # Announce stages
        for s in STAGES:
            _pipeline_stage(task_id, project_id, s["key"], "waiting")
        _pipeline_stage(task_id, project_id, "code_gen", "running")

        # Build callbacks
        on_progress = _make_progress_cb(task_id, project_id)
        on_stage = _make_stage_cb(task_id, project_id)

        # Always include both fields.  A title is commonly the only requirement
        # entered in the UI, while a detailed description may add constraints.
        # Keeping their labels also prevents CLI-backed agents from mistaking
        # the surrounding orchestration prompt for the actual user request.
        task_desc = (
            f"任务标题：{task.title.strip()}\n"
            f"任务详情：{(task.description or task.title).strip()}"
        )
        if feedback:
            task_desc = (
                f"【人工审查反馈 — 请根据以下意见修改代码】\n"
                f"{feedback}\n\n"
                f"【原始任务】\n{task_desc}"
            )

        # Enforce Chinese output for all human-facing content
        task_desc += (
            "\n\n【语言要求】所有输出必须使用中文。代码注释可以使用英文或中文，"
            "但审查报告、问题描述、建议等面向用户的内容必须全部使用中文。"
        )

        # ── Step 0: Proactively inject historical memory ─────
        # Pull relevant project + global memories and prepend them so the agent
        # starts with prior context instead of having to search for it.
        if mem:
            try:
                history = mem.build_memory_context(
                    project_id,
                    f"{task.title} {task.description or ''}",
                    n_results=5,
                    task_id=task_id,
                    agent_id=task.agent_id,
                )
                if history:
                    task_desc = (
                        "【历史经验参考 — 解决类似任务时可借鉴以下经验】\n"
                        f"{history}\n\n"
                        "【当前任务】\n"
                        f"{task_desc}"
                    )
                    _progress(task_id, project_id, "🧠 已载入历史经验参考", "memory")
            except Exception:
                logger.exception("Failed to build memory context")

        # Dispatch to runner
        runner = get_runner(runner_type)
        start_ts = time.time()
        result = runner.run(
            task_description=task_desc,
            workspace=workspace,
            model_name=model_name,
            task_id=task_id,
            project_id=project_id,
            agent_id=task.agent_id,
            on_progress=on_progress,
            on_stage=on_stage,
        )
        elapsed = time.time() - start_ts

        # Pause is cooperative for runners that cannot be interrupted safely.
        # Stop before committing/review creation once the current runner call
        # returns; the task worktree is retained for a later resume.
        db.refresh(task)
        if task.status == TaskStatus.PAUSED:
            _progress(task_id, project_id, "⏸️ 当前执行步骤已结束，任务保持暂停", "paused")
            return

        # Handle runner error
        if result.error:
            _progress(task_id, project_id, f"❌ 执行失败：{result.error[:200]}", "error")
            _fail_task(db, task, result.error, runner_type)
            return

        _progress(task_id, project_id, f"✅ 流水线执行完成（耗时 {elapsed:.0f}s）", "pipeline_done")

        # Extract the final output
        summary = result.summary
        summary_len = len(summary)

        _progress(task_id, project_id, f"📄 审查报告已生成（{summary_len} 字符）", "report_done")

        # ── Step 4: Commit & Diff ──────────────────────────────────
        _progress(task_id, project_id, "💾 正在提交代码变更到 Git...", "commit")
        commit_hash = git.commit(workspace, f"Task #{task.id} — agent changes")
        if commit_hash:
            _progress(task_id, project_id, f"📌 已提交：{commit_hash[:7]}", "committed")

        _progress(task_id, project_id, "📊 正在生成代码差异对比...", "diff")
        diff = git.diff_vs_master(workspace)
        if not diff or diff == "":
            diff = "# No code changes detected"
            _progress(task_id, project_id, "⚠️ 未检测到代码变更", "diff_empty")
        else:
            diff_lines = diff.count('\n')
            _progress(task_id, project_id, f"📊 代码差异：{diff_lines} 行", "diff_done")

        # Push code preview
        if diff and diff != "# No code changes detected":
            broadcast_sync("code_preview", {
                "task_id": task_id,
                "project_id": project_id,
                "diff": diff,
                "timestamp": _now_iso(),
            })

        # A pause may arrive while Git commit/diff work is in progress. Do not
        # expose a review that resume would immediately supersede.
        db.refresh(task)
        if task.status == TaskStatus.PAUSED:
            _progress(task_id, project_id, "⏸️ 代码已保留在任务分支，任务保持暂停", "paused")
            return

        # Store review
        review = Review(
            task_id=task.id,
            project_id=project_id,
            diff_content=diff,
            agent_review_summary=summary,
        )
        db.add(review)
        db.commit()
        db.refresh(review)

        # Start a vote round for every generated review. All project members
        # are invited by default; an owner/admin may refine the list before
        # anyone votes.
        reviewer_ids = [row[0] for row in db.query(ProjectMember.user_id).filter(
            ProjectMember.project_id == project_id
        ).all()]
        approval_percent = max(1, min(100, task.approval_percent or 50))
        required_approvals = max(
            1,
            math.ceil(len(reviewer_ids) * approval_percent / 100),
        )
        db.add(ReviewRound(review_id=review.id, required_approvals=required_approvals))
        db.add_all([ReviewReviewer(review_id=review.id, user_id=user_id) for user_id in reviewer_ids])
        db.commit()

        # ── Save reusable task outcome to Agent + project memory ─────
        if mem:
            try:
                memory_doc = f"Task #{task_id} ({task.title}) [{runner_type}]: {summary[:500]}"
                memory_metadata = {
                    "type": "review_result",
                    "task_id": str(task_id),
                    "project_id": str(project_id),
                    "agent_id": str(task.agent_id),
                    "runner_type": runner_type,
                }
                mem.add_agent_memory(task.agent_id, memory_doc, memory_metadata)
                mem.add_project_memory(project_id, memory_doc, memory_metadata)
            except Exception:
                logger.exception("Failed to record task outcome in hierarchical memory")

        # Switch back to master
        _progress(task_id, project_id, "🔙 切换回主分支，清理工作区...", "cleanup")
        # The task worktree remains on its task branch for review and merge.

        # Push review created
        broadcast_sync("review_update", {
            "id": review.id,
            "task_id": task.id,
            "project_id": project_id,
            "status": "pending",
        })

        # Check if task was paused while pipeline was running
        db.refresh(task)
        if task.status == TaskStatus.PAUSED:
            db.query(ReviewVote).filter(ReviewVote.review_id == review.id).delete()
            db.query(ReviewReviewer).filter(ReviewReviewer.review_id == review.id).delete()
            db.query(ReviewRound).filter(ReviewRound.review_id == review.id).delete()
            db.delete(review)
            db.commit()
            _progress(task_id, project_id, "⏸️ 任务已被暂停，保留工作分支", "paused")
            logger.info(f"Task {task_id} paused by user, keeping branch {branch_name}")
            return

        # Update task & agent status → reviewing
        task.status = TaskStatus.REVIEWING
        task.completed_at = datetime.now(timezone.utc)
        agent = db.get(Agent, task.agent_id)
        if agent:
            agent.status = AgentStatus.DONE
        db.commit()

        _progress(task_id, project_id, "🎉 执行完毕，等待人工审查", "done")

        broadcast_sync("task_update", {
            "id": task.id, "project_id": project_id, "status": "reviewing",
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        })
        broadcast_sync("agent_update", {
            "id": task.agent_id, "status": "done",
            "last_task_id": task_id, "last_task_status": "reviewing",
        })

        # ── Push system message: task awaiting review ──
        try:
            from app.services import message_service as msg
            from app.models.models import MessageCategory, MessageLevel
            msg.push(
                title="任务待审核",
                body=f"任务 #{task_id}（{task.title}）已生成代码，等待人工审查。",
                category=MessageCategory.REVIEW,
                level=MessageLevel.WARNING,
                project_id=project_id,
                link=f"/reviews?task_id={task_id}",
            )
        except Exception:
            pass

        logger.info(f"Task {task_id} [{runner_type}] reviewing, review #{review.id} stored")

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        try:
            _fail_task(db, task, str(e))
        except Exception:
            pass
    finally:
        # Clean up the per-task (ephemeral) memory collection so ChromaDB does
        # not accumulate orphaned collections after every run.
        if mem:
            try:
                mem.delete_task_memory(task_id)
            except Exception:
                pass
        db.close()


def _fail_task(db, task: Task | None, error: str, runner_type: str = "unknown"):
    from app.api.ws import broadcast_sync

    if task is None:
        return

    # Don't overwrite if task was paused by user
    db.refresh(task)
    if task.status == TaskStatus.PAUSED:
        logger.info(f"Task {task.id} was paused, not marking as failed")
        return

    project_id = task.project_id
    task_id = task.id

    _progress(task_id, project_id, f"❌ 执行失败 [{runner_type}]：{error[:200]}", "error")

    task.status = TaskStatus.FAILED
    task.completed_at = datetime.now(timezone.utc)
    agent = db.get(Agent, task.agent_id)
    if agent:
        agent.status = AgentStatus.IDLE
    db.commit()

    # Preserve failure lessons for both the assigned Agent and the project so
    # future work can avoid repeating the same issue.
    if mem:
        try:
            memory_doc = f"Task #{task_id} ({task.title}) [{runner_type}] 执行失败：{error[:300]}"
            memory_metadata = {
                "type": "error",
                "task_id": str(task_id),
                "project_id": str(project_id),
                "agent_id": str(task.agent_id),
                "runner_type": runner_type,
            }
            mem.add_agent_memory(task.agent_id, memory_doc, memory_metadata)
            mem.add_project_memory(project_id, memory_doc, memory_metadata)
        except Exception:
            logger.exception("Failed to record task failure in hierarchical memory")

    broadcast_sync("task_update", {
        "id": task.id, "project_id": project_id, "status": "failed",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    })
    broadcast_sync("agent_update", {"id": task.agent_id, "status": "idle"})

    # ── Push system message: task failed ──
    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        msg.push(
            title="任务执行失败",
            body=f"任务 #{task_id}（{task.title}）执行失败：{error[:200]}",
            category=MessageCategory.TASK,
            level=MessageLevel.ERROR,
            project_id=project_id,
            link=f"/tasks",
        )
    except Exception:
        pass
