"""Agent pipeline runner — bridges FastAPI ↔ CrewAI.

Runs in a background thread via FastAPI BackgroundTasks to avoid blocking the event loop.
Integrates with the ChromaDB 3-layer memory system.
Pushes real-time progress via WebSocket `task_progress` events.
"""

import logging
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus, Agent, AgentStatus, Review, Project
from app.services import git_service as git
from app.services import memory_service as mem

logger = logging.getLogger(__name__)


def _progress(task_id: int, project_id: int, message: str, step: str = ""):
    """Push a progress update via WebSocket + record in task memory."""
    from app.api.ws import broadcast_sync

    broadcast_sync("task_progress", {
        "task_id": task_id,
        "project_id": project_id,
        "message": message,
        "step": step,
    })
    try:
        mem.add_task_memory(task_id, message, {"type": "progress", "step": step})
    except Exception:
        pass


def run_agent_pipeline(task_id: int):
    """Execute the full agent pipeline for a given task.

    Called by FastAPI's BackgroundTasks — runs in a thread pool.
    """
    from app.api.ws import broadcast_sync

    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        project_id = task.project_id

        # Update status → running
        task.status = TaskStatus.RUNNING
        db.commit()
        broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "running"})

        _progress(task_id, project_id, "任务开始执行", "start")
        _progress(task_id, project_id, f"任务目标：{task.title}", "goal")
        if task.description:
            _progress(task_id, project_id, f"任务描述：{task.description}", "desc")

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
            broadcast_sync("agent_update", {"id": agent.id, "status": "working"})

        # ── Step 1: Prepare workspace ──────────────────────────────
        _progress(task_id, project_id, "正在准备项目工作空间...", "prepare")
        workspace = project.workspace_path

        # ── Step 2: Create task branch ─────────────────────────────
        branch_name = f"task/{task.id}"
        _progress(task_id, project_id, f"创建 Git 工作分支：{branch_name}", "branch")
        git.create_branch(workspace, branch_name)

        # ── Step 3: Build CrewAI pipeline ──────────────────────────
        _progress(task_id, project_id, f"启动 Agent「{agent_name}」", "agent_start")
        _progress(task_id, project_id, f"使用模型：{model_name}", "model")

        from agent_service.crews.review_pipeline import build_crew

        crew = build_crew(
            workspace,
            model_name,
            task_id=task_id,
            project_id=project_id,
        )

        # ── Step 4: Run pipeline ───────────────────────────────────
        _progress(task_id, project_id, "第 1/4 步：代码工程师正在生成代码...", "step_1_codegen")
        _progress(task_id, project_id, "Agent 正在查看现有代码结构，分析需求...", "step_1_detail")

        result = crew.kickoff(inputs={"task_description": task.description or task.title})

        _progress(task_id, project_id, "第 2/4 步：代码审查员正在检查代码质量...", "step_2_review")
        _progress(task_id, project_id, "第 3/4 步：安全审查员正在扫描安全漏洞...", "step_3_security")
        _progress(task_id, project_id, "第 4/4 步：正在汇总审查报告...", "step_4_summary")

        # Extract the final output (summarizer's report)
        summary = str(result) if result else ""
        summary_len = len(summary)

        _progress(task_id, project_id, f"审查报告已生成（{summary_len} 字符）", "report_done")

        # ── Step 5: Commit & Diff ──────────────────────────────────
        _progress(task_id, project_id, "正在提交代码变更到 Git...", "commit")
        commit_hash = git.commit(workspace, f"Task #{task.id} — agent changes")
        if commit_hash:
            _progress(task_id, project_id, f"已提交：{commit_hash[:7]}", "committed")

        _progress(task_id, project_id, "正在生成代码差异对比...", "diff")
        diff = git.diff_vs_master(workspace)
        if not diff or diff == "":
            diff = "# No code changes detected"
            _progress(task_id, project_id, "未检测到代码变更", "diff_empty")
        else:
            diff_lines = diff.count('\n')
            _progress(task_id, project_id, f"代码差异：{diff_lines} 行", "diff_done")

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
        _progress(task_id, project_id, "切换回主分支，清理工作区...", "cleanup")
        git.switch_branch(workspace, "master")

        # Push review created
        broadcast_sync("review_update", {
            "id": review.id,
            "task_id": task.id,
            "project_id": project_id,
            "status": "pending",
        })

        # Update task & agent status → done
        task.status = TaskStatus.REVIEWING
        agent = db.query(Agent).get(task.agent_id)
        if agent:
            agent.status = AgentStatus.DONE
        db.commit()

        _progress(task_id, project_id, "执行完毕，等待人工审查", "done")

        broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "reviewing"})
        broadcast_sync("agent_update", {"id": task.agent_id, "status": "done"})

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

    project_id = task.project_id
    task_id = task.id

    _progress(task_id, project_id, f"执行失败：{error[:200]}", "error")

    task.status = TaskStatus.FAILED
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

    broadcast_sync("task_update", {"id": task.id, "project_id": project_id, "status": "failed"})
    broadcast_sync("agent_update", {"id": task.agent_id, "status": "idle"})
