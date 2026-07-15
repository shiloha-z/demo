"""Agent pipeline runner — bridges FastAPI ↔ CrewAI.

Runs in a background thread via FastAPI BackgroundTasks to avoid blocking the event loop.
Integrates with the ChromaDB 3-layer memory system.
Pushes real-time progress via WebSocket `task_progress` and `pipeline_stage` events.
"""

import logging
import time
from datetime import datetime, timezone
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus, Agent, AgentStatus, Review, Project
from app.services import git_service as git
from app.services import memory_service as mem

logger = logging.getLogger(__name__)

# ── Stage definitions ─────────────────────────────────────────────────

STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",  "desc": "正在生成代码..."},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",   "desc": "正在检查代码质量..."},
    {"key": "security",   "label": "安全审查员", "icon": "shield","desc": "正在扫描安全漏洞..."},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",  "desc": "正在汇总审查报告..."},
]

STAGE_BY_TASK_PREFIX: dict[str, str] = {
    "任务描述": "code_gen",
    "请审查刚才代码工程师": "reviewer",
    "请审查刚才代码工程师生成的代码的安全性": "security",
    "请将代码审查员和安全审查员的审查意见汇总": "summarizer",
}


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


# ── Task callback factory (hooks into CrewAI sequential execution) ────

def _make_task_callback(task_id: int, project_id: int, workspace: str):
    """Return a callback that fires after each CrewAI task completes.

    CrewAI calls task_callback(task_output) where task_output has:
      - description (str) — the task description text
      - agent (Agent) — the agent that executed
      - raw (str) — the output text
    """

    stage_order = ["code_gen", "reviewer", "security", "summarizer"]
    completed: list[str] = []

    def on_task_done(task_output):
        # Infer which stage just completed from the task description
        desc = getattr(task_output, "description", "")
        stage_key = None
        for prefix, key in STAGE_BY_TASK_PREFIX.items():
            if prefix in desc:
                stage_key = key
                break

        if not stage_key:
            # Fallback: assign by order
            idx = len(completed)
            if idx < len(stage_order):
                stage_key = stage_order[idx]
            else:
                return

        completed.append(stage_key)
        _pipeline_stage(task_id, project_id, stage_key, "done")

        # After code_gen stage, push a real-time code diff preview
        if stage_key == "code_gen":
            try:
                diff = git.get_diff(workspace)
                if diff:
                    from app.api.ws import broadcast_sync
                    broadcast_sync("code_preview", {
                        "task_id": task_id,
                        "project_id": project_id,
                        "diff": diff,
                        "timestamp": _now_iso(),
                    })
                    _progress(task_id, project_id, "代码预览已推送", "code_preview")
            except Exception:
                pass

        # Record stage completion to memory
        try:
            mem.add_task_memory(
                task_id,
                f"Stage completed: {stage_key}",
                {"type": "stage_done", "stage": stage_key, "timestamp": _now_iso()},
            )
        except Exception:
            pass

    return on_task_done


# ── Main entry point ──────────────────────────────────────────────────

def run_agent_pipeline(task_id: int):
    """Execute the full agent pipeline for a given task.

    Called by FastAPI's BackgroundTasks — runs in a thread pool.
    """
    from app.api.ws import broadcast_sync

    db = SessionLocal()
    task = None
    try:
        task = db.query(Task).get(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        project_id = task.project_id
        start_time = _now_iso()

        # Update status → running
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        broadcast_sync("task_update", {
            "id": task.id, "project_id": project_id, "status": "running",
            "started_at": task.started_at.isoformat(),
        })

        _progress(task_id, project_id, "🚀 任务开始执行", "start")
        _progress(task_id, project_id, f"📋 任务目标：{task.title}", "goal")
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

        # ── Step 2: Create task branch ─────────────────────────────
        branch_name = f"task/{task.id}"
        _progress(task_id, project_id, f"🌿 创建 Git 工作分支：{branch_name}", "branch")
        git.create_branch(workspace, branch_name)

        # ── Step 3: Build CrewAI pipeline ──────────────────────────
        _progress(task_id, project_id, f"🤖 启动 Agent「{agent_name}」", "agent_start")
        _progress(task_id, project_id, f"🧠 使用模型：{model_name}", "model")

        # Announce all stages as waiting, then mark first as running
        for s in STAGES:
            _pipeline_stage(task_id, project_id, s["key"], "waiting")
        _pipeline_stage(task_id, project_id, "code_gen", "running")

        from agent_service.crews.review_pipeline import build_crew

        task_callback = _make_task_callback(task_id, project_id, workspace)
        crew = build_crew(
            workspace,
            model_name,
            task_id=task_id,
            project_id=project_id,
            task_callback=task_callback,
        )

        # ── Step 4: Run pipeline ───────────────────────────────────
        _progress(task_id, project_id, "⚙️  第 1/4 步：代码工程师正在生成代码...", "step_1_codegen")
        _progress(task_id, project_id, "🔍 Agent 正在查看现有代码结构，分析需求...", "step_1_detail")

        start_ts = time.time()
        result = crew.kickoff(inputs={"task_description": task.description or task.title})
        elapsed = time.time() - start_ts

        _progress(task_id, project_id, f"✅ 代码工程师完成（耗时 {elapsed:.0f}s）", "step_1_done")

        # Push remaining stage done events (in case callbacks didn't fire)
        _pipeline_stage(task_id, project_id, "reviewer", "done")
        _progress(task_id, project_id, "✅ 第 2/4 步：代码审查完成", "step_2_done")
        _pipeline_stage(task_id, project_id, "security", "done")
        _progress(task_id, project_id, "✅ 第 3/4 步：安全审查完成", "step_3_done")
        _pipeline_stage(task_id, project_id, "summarizer", "done")
        _progress(task_id, project_id, "✅ 第 4/4 步：审查报告汇总完成", "step_4_done")

        # Extract the final output (summarizer's report)
        summary = str(result) if result else ""
        summary_len = len(summary)

        _progress(task_id, project_id, f"📄 审查报告已生成（{summary_len} 字符）", "report_done")

        # ── Step 5: Commit & Diff ──────────────────────────────────
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
                f"Task #{task_id} ({task.title}): {summary[:500]}",
                {"type": "review_result", "task_id": str(task_id), "status": "pending"},
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

        logger.info(f"Task {task_id} reviewing, review #{review.id} stored")

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        try:
            _fail_task(db, task, str(e))
        except Exception:
            pass
    finally:
        db.close()


def _fail_task(db, task: Task, error: str):
    from app.api.ws import broadcast_sync

    if task is None:
        return

    project_id = task.project_id
    task_id = task.id

    _progress(task_id, project_id, f"❌ 执行失败：{error[:200]}", "error")

    task.status = TaskStatus.FAILED
    task.completed_at = datetime.now(timezone.utc)
    agent = db.query(Agent).get(task.agent_id)
    if agent:
        agent.status = AgentStatus.IDLE
    review = Review(
        task_id=task.id,
        project_id=project_id,
        diff_content="",
        agent_review_summary=f"Execution failed:\n{error}",
    )
    db.add(review)
    db.commit()

    # Record failure in memory
    try:
        mem.add_task_memory(task.id, f"Task failed: {error}", {"type": "error"})
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
