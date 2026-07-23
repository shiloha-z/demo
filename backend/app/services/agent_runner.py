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
from app.core.config import settings
from app.models.models import Task, TaskStatus, Agent, AgentStatus, QualityGateRun, Review, ReviewRound, ReviewReviewer, ReviewVote, Project, ProjectMember
from app.services import git_service as git
from app.services import quality_gate_service as quality_gates
from app.services.audit_service import record as audit_record


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

class _TaskPaused(Exception):
    """Raised inside a runner callback when the user has paused the task."""


def _make_progress_cb(task_id: int, project_id: int):
    """Create a progress callback that also checks for user-requested pause.

    Every time the runner reports progress the callback queries the task
    status.  When the user clicks pause the next progress report (which may
    happen many times per second during agent execution) raises
    ``_TaskPaused``, which causes the pipeline to bail out cleanly instead
    of running to the next coarse-grained checkpoint.
    """
    def _on_progress(msg: str, step: str = ""):
        _progress(task_id, project_id, msg, step)
        # Check pause only every ~2 seconds to avoid hammering the DB on
        # high-frequency progress callbacks.
        now = time.time()
        if now - getattr(_on_progress, "_last_check", 0) < 2:
            return
        _on_progress._last_check = now  # type: ignore[attr-defined]
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if task and task.status == TaskStatus.PAUSED:
                raise _TaskPaused()
        finally:
            db.close()

    return _on_progress


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
            _fail_task_child_aware(db, task, "Project workspace not found", project_id)
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

        # Resolve the parent task (if this task is a child in a planning tree).
        parent = db.get(Task, task.parent_task_id) if task.parent_task_id else None
        child = parent is not None

        if parent is not None:
            # CHILD TASK: every child reuses the parent's single worktree and
            # branch, so their changes accumulate into ONE combined diff that
            # the parent later aggregates into a single review.
            workspace = parent.worktree_path or git.default_task_worktree_path(project.workspace_path, parent.id)
            branch_name = parent.branch_name or f"task/{parent.id}"
            ok, error = git.ensure_worktree(project.workspace_path, workspace, branch_name)
            if not ok:
                _fail_task_child_aware(db, task, f"无法创建/修复父任务工作树：{error}", project_id)
                return
            if not parent.worktree_path:
                parent.worktree_path = workspace
                parent.branch_name = branch_name
                parent.base_commit = git.head_commit(project.workspace_path, git.get_base_branch(project.workspace_path))
                db.commit()
            _progress(task_id, project_id, f"🌿 子任务复用父任务共享分支：{branch_name}", "branch")
            git.switch_branch(workspace, branch_name)
        else:
            # TOP-LEVEL TASK: isolated worktree + branch.
            workspace = task.worktree_path or git.default_task_worktree_path(project.workspace_path, task.id)

            # ── Step 2: Create or reuse task branch ────────────────────
            branch_name = task.branch_name or f"task/{task.id}"
            if conflict_resolution and not git.get_repo(workspace):
                _fail_task_child_aware(db, task, "Conflict worktree not found", project_id)
                return
            if not conflict_resolution:
                ok, error = git.ensure_worktree(project.workspace_path, workspace, branch_name)
                if not ok:
                    _fail_task_child_aware(db, task, f"Could not create task worktree: {error}", project_id)
                    return
                if not task.worktree_path:
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
            if conflict_resolution:
                # Conflict resolution is a targeted fix, not a full redo.
                # Don't show the original task — the agent should ONLY resolve
                # the merge markers, not regenerate code from scratch.
                task_desc = (
                    f"【合并冲突解决 — 请仅修复以下文件的 Git 冲突标记，不要重写或重新生成任何代码！】\n\n"
                    f"{feedback}\n\n"
                    f"重要提醒：你的唯一工作是打开冲突文件，找到 <<<<<<<、=======、>>>>>>> 标记，"
                    f"合并双方的修改（保留双方的有效改动），移除冲突标记，然后提交。"
                    f"不要修改任何非冲突文件，不要重写或重新生成任何代码。"
                )
            else:
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

        # Resolve project-configured reviewer / security agent prompts.
        reviewer_prompt = None
        security_prompt = None
        if task.reviewer_agent_id:
            rev_agent = db.get(Agent, task.reviewer_agent_id)
            if rev_agent and rev_agent.system_prompt:
                reviewer_prompt = rev_agent.system_prompt
        if task.security_agent_id:
            sec_agent = db.get(Agent, task.security_agent_id)
            if sec_agent and sec_agent.system_prompt:
                security_prompt = sec_agent.system_prompt

        start_ts = time.time()
        result = runner.run(
            task_description=task_desc,
            workspace=workspace,
            model_name=model_name,
            task_id=task_id,
            project_id=project_id,
            agent_id=task.agent_id,
            enable_planning=bool(agent.enable_planning) if (agent and not child) else False,
            max_subtasks=int(agent.max_subtasks) if (agent and not child and agent.max_subtasks) else 6,
            on_progress=on_progress,
            on_stage=on_stage,
            reviewer_prompt=reviewer_prompt,
            security_prompt=security_prompt,
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
            _fail_task_child_aware(db, task, result.error, project_id, runner_type)
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

        # ── Child tasks: no independent review ──────────────────────
        # All changes were already committed to the shared parent branch.  Mark
        # this subtask complete and advance the planning tree (chain the next
        # sibling, or aggregate a single parent review once all are done).
        if parent is not None:
            _complete_child_task(db, task, parent, project_id, branch_name)
            return

        # Top-level task: build the review + gate + voting round via the
        # shared helper (children never reach this point — they return earlier).
        _persist_review(db, task, runner_type, workspace, commit_hash, diff, summary)
        return

    except _TaskPaused:
        # User requested pause during execution.  Refresh the DB row to
        # confirm it's still PAUSED and leave the worktree + agent state
        # intact so the task can be resumed later.
        db.refresh(task)
        if task.status == TaskStatus.PAUSED:
            _progress(task_id, project_id, "⏸️ 任务已暂停，工作分支已保留", "paused")
            logger.info(f"Task {task_id} paused by user mid-execution")
        else:
            # Race: pause was set but something else flipped the status.
            # Treat as a normal failure so the task doesn't get stuck.
            _fail_task_child_aware(db, task, "任务状态不一致：暂停请求后状态已变更", project_id)
    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        try:
            _fail_task_child_aware(db, task, str(e), project_id)
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


def _fail_task_child_aware(db, task, error, project_id, runner_type: str = "unknown"):
    """_fail_task, plus advance the planning tree if *task* is a child."""
    _fail_task(db, task, error, runner_type)
    if task and task.parent_task_id:
        _on_child_finished(db, task.id, project_id)


def _complete_child_task(db, task, parent, project_id, branch_name):
    """Mark a finished child task as merged into the parent branch."""
    from app.api.ws import broadcast_sync
    task.status = TaskStatus.SUBTASK_DONE
    task.completed_at = datetime.now(timezone.utc)
    db.commit()
    _progress(task.id, project_id, f"✅ 子任务完成，改动已并入共享分支 {branch_name}", "subtask_done")
    broadcast_sync("task_update", {
        "id": task.id, "project_id": project_id, "status": "subtask_done",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    })
    _on_child_finished(db, task.id, project_id)


def _on_child_finished(db, task_id, project_id):
    """Advance a planning tree once a child task ends.

    Children run sequentially against the parent's shared branch.  While some
    siblings are still pending we start the next one; once every child is
    terminal we either fail the parent (any child failed) or aggregate all
    their changes into a SINGLE parent review.
    """
    from app.api.ws import broadcast_sync
    from app.services.execution_service import enqueue_agent_run

    task = db.get(Task, task_id)
    if not task or not task.parent_task_id:
        return
    parent = db.get(Task, task.parent_task_id)
    if not parent:
        return

    children = db.query(Task).filter(Task.parent_task_id == parent.id).order_by(Task.id).all()
    any_failed = any(c.status == TaskStatus.FAILED for c in children)
    all_terminal = all(
        c.status in (TaskStatus.SUBTASK_DONE, TaskStatus.FAILED) for c in children
    )

    if not all_terminal:
        nxt = db.query(Task).filter(
            Task.parent_task_id == parent.id, Task.status == TaskStatus.PENDING
        ).order_by(Task.id).first()
        if nxt:
            claimed = db.query(Task).filter(
                Task.id == nxt.id, Task.status == TaskStatus.PENDING
            ).update(
                {Task.status: TaskStatus.RUNNING, Task.started_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
            db.commit()
            if claimed:
                broadcast_sync("task_update", {
                    "id": nxt.id, "project_id": project_id, "status": "running",
                    "started_at": nxt.started_at.isoformat() if nxt.started_at else None,
                })
                enqueue_agent_run(nxt.id)
        if parent.status == TaskStatus.PLANNING:
            parent.status = TaskStatus.SUBTASK_RUNNING
            db.commit()
            broadcast_sync("task_update", {
                "id": parent.id, "project_id": project_id, "status": "subtask_running",
            })
        return

    # Every child has finished.
    if any_failed:
        parent.status = TaskStatus.FAILED
        parent.completed_at = datetime.now(timezone.utc)
        db.commit()
        broadcast_sync("task_update", {
            "id": parent.id, "project_id": project_id, "status": "failed",
        })
        _free_child_agents(db, children)
        return

    _finalize_parent_review(db, parent, project_id)


def _finalize_parent_review(db, parent, project_id):
    """Aggregate every child's changes into a single parent Review (+ gate)."""
    # Idempotency: never create the parent review twice.
    if db.query(Review).filter(Review.task_id == parent.id).first():
        return
    if parent.status == TaskStatus.REVIEWING:
        return

    workspace = parent.worktree_path
    commit_hash = git.head_commit(workspace) if workspace else ""
    diff = git.diff_vs_master(workspace) if workspace else ""
    if not diff or diff == "":
        diff = "# No code changes detected"

    children = db.query(Task).filter(Task.parent_task_id == parent.id).order_by(Task.id).all()
    summary = (
        f"本审查由父任务「{parent.title}」的 {len(children)} 个子任务合并而成。"
        "所有子任务的改动落在同一分支，统一提交一次人工审核：\n"
    )
    for c in children:
        summary += f"- 子任务 #{c.id} {c.title}\n"

    parent_agent = db.get(Agent, parent.agent_id)
    runner_type = parent_agent.runner_type if parent_agent else "crewai"

    # Same review + gate + voting-round creation a top-level task uses, so the
    # aggregated review behaves identically (one combined change, one approval).
    _persist_review(db, parent, runner_type, workspace, commit_hash, diff, summary)

    # Free the agents that worked on the children (the parent's own agent is
    # marked DONE inside _persist_review).
    _free_child_agents(db, children)


def _persist_review(db, task, runner_type, workspace, commit_hash, diff, summary):
    """Create the Review + voting round + quality gate for *task* and move it
    to REVIEWING.  Shared by top-level tasks and the parent of a planning tree.
    """
    from app.api.ws import broadcast_sync
    project_id = task.project_id

    review = Review(
        task_id=task.id,
        project_id=project_id,
        diff_content=diff,
        agent_review_summary=summary,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    reviewer_ids = [row[0] for row in db.query(ProjectMember.user_id).filter(
        ProjectMember.project_id == project_id
    ).all()]
    approval_percent = max(1, min(100, task.approval_percent or 50))
    required_approvals = max(1, math.ceil(len(reviewer_ids) * approval_percent / 100))
    db.add(ReviewRound(review_id=review.id, required_approvals=required_approvals))
    db.add_all([ReviewReviewer(review_id=review.id, user_id=user_id) for user_id in reviewer_ids])
    db.commit()

    if settings.QUALITY_GATE_ENABLED:
        checked_commit = commit_hash or git.head_commit(workspace)
        changed_files = sorted(git.changed_files_vs_base(workspace, checked_commit))
        _progress(task.id, project_id, "🛡️ 正在执行人工审批前确定性检查...", "quality_gate")
        gate_run = quality_gates.execute_and_persist(
            db, task=task, review=review, workspace=workspace,
            commit_hash=checked_commit, changed_files=changed_files,
        )
        if gate_run.status == "passed":
            _progress(task.id, project_id, "✅ 七项确定性检查全部通过，可以开始人工审批", "quality_gate_passed")
        else:
            _progress(task.id, project_id, f"⛔ {gate_run.summary}，请打回 Agent 修改", "quality_gate_failed")
    else:
        _progress(task.id, project_id, "ℹ️ 确定性门禁已关闭，跳过检查，直接进入人工审批", "quality_gate")
        attempt = db.query(QualityGateRun).filter(QualityGateRun.task_id == task.id).count() + 1
        gate_run = QualityGateRun(
            task_id=task.id, review_id=review.id, attempt=attempt,
            commit_hash=commit_hash or git.head_commit(workspace),
            status="passed", results_json="[]",
            summary="确定性门禁已关闭，跳过全部检查",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(gate_run)
        db.commit()
        db.refresh(gate_run)
        broadcast_sync("quality_gate_update", {
            "id": gate_run.id, "task_id": task.id, "project_id": project_id,
            "review_id": review.id, "status": "passed", "checks": [],
        })

    if mem:
        try:
            memory_doc = f"Task #{task.id} ({task.title}) [{runner_type}]: {summary[:500]}"
            memory_metadata = {
                "type": "review_result", "task_id": str(task.id),
                "project_id": str(project_id), "agent_id": str(task.agent_id),
                "runner_type": runner_type,
            }
            mem.add_agent_memory(task.agent_id, memory_doc, memory_metadata)
            mem.add_project_memory(project_id, memory_doc, memory_metadata)
        except Exception:
            logger.exception("Failed to record task outcome in hierarchical memory")

    broadcast_sync("review_update", {
        "id": review.id, "task_id": task.id, "project_id": project_id, "status": "pending",
    })

    # Defensive: the earlier pause checks already short-circuit a paused task
    # before review creation, so this is a no-op in practice but keeps the
    # behaviour identical to the previous inline implementation.
    db.refresh(task)
    if task.status == TaskStatus.PAUSED:
        db.query(QualityGateRun).filter(QualityGateRun.review_id == review.id).delete()
        db.query(ReviewVote).filter(ReviewVote.review_id == review.id).delete()
        db.query(ReviewReviewer).filter(ReviewReviewer.review_id == review.id).delete()
        db.query(ReviewRound).filter(ReviewRound.review_id == review.id).delete()
        db.delete(review)
        db.commit()
        _progress(task.id, project_id, "⏸️ 任务已被暂停，保留工作分支", "paused")
        logger.info(f"Task {task.id} paused by user, keeping branch {task.branch_name}")
        return

    task.status = TaskStatus.REVIEWING
    task.completed_at = datetime.now(timezone.utc)
    db.commit()

    final_message = (
        "🎉 执行完毕，门禁已通过，等待人工审查"
        if gate_run.status == "passed"
        else "⚠️ 执行完毕，门禁未通过，等待人工打回修改"
    )
    _progress(task.id, project_id, final_message, "done")

    # Agent is only "done" when no other tasks are still using it.
    other_active = db.query(Task.id).filter(
        Task.agent_id == task.agent_id,
        Task.id != task.id,
        Task.status.in_([TaskStatus.RUNNING, TaskStatus.CONFLICT_RESOLUTION, TaskStatus.PLANNING, TaskStatus.SUBTASK_RUNNING]),
    ).first()
    agent_status = "done" if not other_active else "working"
    db.query(Agent).filter(Agent.id == task.agent_id).update(
        {Agent.status: AgentStatus.DONE if not other_active else AgentStatus.WORKING},
        synchronize_session=False,
    )
    db.commit()

    broadcast_sync("task_update", {
        "id": task.id, "project_id": project_id, "status": "reviewing",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    })
    broadcast_sync("agent_update", {
        "id": task.agent_id, "status": agent_status,
        "last_task_id": task.id, "last_task_status": "reviewing",
    })

    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        gate_passed = gate_run.status == "passed"
        msg.push(
            title="任务待审核" if gate_passed else "任务门禁未通过",
            body=(
                f"任务 #{task.id}（{task.title}）门禁已通过，等待人工审查。"
                if gate_passed
                else f"任务 #{task.id}（{task.title}）确定性检查未通过，请查看失败项并打回 Agent 修改。"
            ),
            category=MessageCategory.REVIEW,
            level=MessageLevel.WARNING if gate_passed else MessageLevel.ERROR,
            project_id=project_id,
            link=f"/reviews?task_id={task.id}",
        )
    except Exception:
        pass

    logger.info(f"Task {task.id} [{runner_type}] reviewing, review #{review.id} stored")


def _free_child_agents(db, children):
    for c in children:
        try:
            _maybe_idle_agent(db, c.agent_id)
        except Exception:
            pass


def _maybe_idle_agent(db, agent_id: int) -> None:
    """Set the agent to IDLE only when no other task is still using it."""
    other_active = db.query(Task.id).filter(
        Task.agent_id == agent_id,
        Task.status.in_([TaskStatus.RUNNING, TaskStatus.CONFLICT_RESOLUTION, TaskStatus.PLANNING, TaskStatus.SUBTASK_RUNNING]),
    ).first()
    if not other_active:
        db.query(Agent).filter(Agent.id == agent_id).update(
            {Agent.status: AgentStatus.IDLE}, synchronize_session=False,
        )
        db.commit()
        try:
            from app.api.ws import broadcast_sync
            broadcast_sync("agent_update", {"id": agent_id, "status": "idle"})
        except Exception:
            pass


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
    db.commit()
    if agent:
        _maybe_idle_agent(db, agent.id)

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
