"""Agent pipeline runner — bridges FastAPI ↔ Agent Runners.

Runs in a background thread via FastAPI BackgroundTasks to avoid blocking the event loop.
Integrates with the ChromaDB 3-layer memory system.
Pushes real-time progress via WebSocket `task_progress` and `pipeline_stage` events.

Supports multiple runner backends via agent.runner_type:
  - crewai:     4-agent CrewAI sequential pipeline
  - claude_code: Anthropic Claude Agent SDK
  - opencode:    OpenCode CLI
"""

import logging
import time
from datetime import datetime, timezone
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus, Agent, AgentStatus, Review, Project
from app.services import git_service as git
from app.services import memory_service as mem

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
    """Push a progress update via WebSocket + record in task memory."""
    from app.api.ws import broadcast_sync

    payload = {
        "task_id": task_id,
        "project_id": project_id,
        "message": message,
        "step": step,
        "timestamp": _now_iso(),
    }
    broadcast_sync("task_progress", payload)
    try:
        mem.add_task_memory(task_id, message, {"type": "progress", "step": step, "timestamp": payload["timestamp"]})
    except Exception:
        pass


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

def run_agent_pipeline(task_id: int, feedback: str = ""):
    """Execute the full agent pipeline for a given task.

    Dispatches to the correct runner based on agent.runner_type.
    Called by FastAPI's BackgroundTasks — runs in a thread pool.

    If `feedback` is provided, the pipeline runs in "revision" mode:
    - Reuses the existing task branch (does not create a new one from master)
    - Prepends the human feedback to the task description so the agent can address it
    """
    from app.api.ws import broadcast_sync
    from agent_service.runners.factory import get_runner

    db = SessionLocal()
    task = None
    try:
        task = db.query(Task).get(task_id)
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

        project = db.query(Project).get(project_id)
        if not project or not project.workspace_path:
            _fail_task(db, task, "Project workspace not found")
            return

        # Get the agent
        agent = db.query(Agent).get(task.agent_id)
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
        workspace = project.workspace_path

        # ── Step 2: Create or reuse task branch ────────────────────
        branch_name = f"task/{task.id}"
        if is_revision:
            _progress(task_id, project_id, f"🌿 切换到已有工作分支：{branch_name}", "branch")
            git.switch_branch(workspace, branch_name)
        else:
            _progress(task_id, project_id, f"🌿 创建 Git 工作分支：{branch_name}", "branch")
            git.create_branch(workspace, branch_name)

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

        # Build task description with optional feedback for revision rounds
        task_desc = task.description or task.title
        if feedback:
            task_desc = (
                f"【人工审查反馈 — 请根据以下意见修改代码】\n"
                f"{feedback}\n\n"
                f"【原始任务】\n{task_desc}"
            )

        # Dispatch to runner
        runner = get_runner(runner_type)
        start_ts = time.time()
        result = runner.run(
            task_description=task_desc,
            workspace=workspace,
            model_name=model_name,
            task_id=task_id,
            project_id=project_id,
            on_progress=on_progress,
            on_stage=on_stage,
        )
        elapsed = time.time() - start_ts

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

        # ── Save to project memory ──────────────────────────────────
        try:
            mem.add_project_memory(
                project_id,
                f"Task #{task_id} ({task.title}) [{runner_type}]: {summary[:500]}",
                {"type": "review_result", "task_id": str(task_id), "runner_type": runner_type},
            )
        except Exception:
            pass

        # Switch back to master
        _progress(task_id, project_id, "🔙 切换回主分支，清理工作区...", "cleanup")
        git.switch_branch(workspace, "master")

        # Push review created
        broadcast_sync("review_update", {
            "id": review.id,
            "task_id": task.id,
            "project_id": project_id,
            "status": "pending",
        })

        # Update task & agent status → reviewing
        task.status = TaskStatus.REVIEWING
        task.completed_at = datetime.now(timezone.utc)
        agent = db.query(Agent).get(task.agent_id)
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

        logger.info(f"Task {task_id} [{runner_type}] reviewing, review #{review.id} stored")

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        try:
            _fail_task(db, task, str(e))
        except Exception:
            pass
    finally:
        db.close()


def _fail_task(db, task: Task | None, error: str, runner_type: str = "unknown"):
    from app.api.ws import broadcast_sync

    if task is None:
        return

    project_id = task.project_id
    task_id = task.id

    _progress(task_id, project_id, f"❌ 执行失败 [{runner_type}]：{error[:200]}", "error")

    task.status = TaskStatus.FAILED
    task.completed_at = datetime.now(timezone.utc)
    agent = db.query(Agent).get(task.agent_id)
    if agent:
        agent.status = AgentStatus.IDLE
    review = Review(
        task_id=task.id,
        project_id=project_id,
        diff_content="",
        agent_review_summary=f"Execution failed [{runner_type}]:\n{error}",
    )
    db.add(review)
    db.commit()

    # Record failure in memory
    try:
        mem.add_task_memory(task.id, f"Task failed [{runner_type}]: {error}", {"type": "error"})
    except Exception:
        pass

    # Switch back to master
    project = db.query(Project).get(project_id)
    if project and project.workspace_path:
        git.switch_branch(project.workspace_path, "master")

    broadcast_sync("task_update", {
        "id": task.id, "project_id": project_id, "status": "failed",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    })
    broadcast_sync("agent_update", {"id": task.agent_id, "status": "idle"})
