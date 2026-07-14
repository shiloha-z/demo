"""Agent pipeline runner — bridges FastAPI ↔ CrewAI.

Runs in a background thread via FastAPI BackgroundTasks to avoid blocking the event loop.
"""

import logging
from app.core.database import SessionLocal
from app.models.models import Task, TaskStatus, Agent, AgentStatus, Review, Project
from app.services import git_service as git

logger = logging.getLogger(__name__)


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

        # Update status → running
        task.status = TaskStatus.RUNNING
        db.commit()
        broadcast_sync("task_update", {"id": task.id, "project_id": task.project_id, "status": "running"})

        project = db.query(Project).get(task.project_id)
        if not project or not project.workspace_path:
            _fail_task(db, task, "Project workspace not found")
            return

        # Build and run the CrewAI pipeline
        from agent_service.crews.review_pipeline import build_crew

        # Get the agent's model preference
        agent = db.query(Agent).get(task.agent_id)
        model_name = agent.model if agent and agent.model else "deepseek-chat"

        # Push agent status → working
        if agent:
            agent.status = AgentStatus.WORKING
            db.commit()
            broadcast_sync("agent_update", {"id": agent.id, "status": "working"})

        # ── Branch isolation: create task branch ──────────────────────
        branch_name = f"task/{task.id}"
        git.create_branch(project.workspace_path, branch_name)

        crew = build_crew(project.workspace_path, model_name)
        result = crew.kickoff(inputs={"task_description": task.description or task.title})

        # Extract the final output (summarizer's report)
        summary = str(result) if result else ""

        # Commit changes on task branch (so they survive branch switches)
        git.commit(project.workspace_path, f"Task #{task.id} — agent changes")

        # Get diff — only this task's changes vs master
        diff = git.diff_vs_master(project.workspace_path)
        if not diff:
            diff = "# No code changes detected"

        # Store review
        review = Review(
            task_id=task.id,
            project_id=task.project_id,
            diff_content=diff,
            agent_review_summary=summary,
        )
        db.add(review)
        db.commit()
        db.refresh(review)

        # Switch back to master — keep working tree clean for file manager
        git.switch_branch(project.workspace_path, "master")

        # Push review created
        broadcast_sync("review_update", {
            "id": review.id,
            "task_id": task.id,
            "project_id": task.project_id,
            "status": "pending",
        })

        # Update task & agent status → done
        task.status = TaskStatus.COMPLETED
        agent = db.query(Agent).get(task.agent_id)
        if agent:
            agent.status = AgentStatus.DONE
        db.commit()

        broadcast_sync("task_update", {"id": task.id, "project_id": task.project_id, "status": "completed"})
        broadcast_sync("agent_update", {"id": task.agent_id, "status": "done"})

        logger.info(f"Task {task_id} completed, review #{review.id} stored")

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

    task.status = TaskStatus.FAILED
    agent = db.query(Agent).get(task.agent_id)
    if agent:
        agent.status = AgentStatus.IDLE
    review = Review(
        task_id=task.id,
        project_id=task.project_id,
        diff_content="",
        agent_review_summary=f"Execution failed:\n{error}",
    )
    db.add(review)
    db.commit()

    # Switch back to master
    project = db.query(Project).get(task.project_id)
    if project and project.workspace_path:
        git.switch_branch(project.workspace_path, "master")

    broadcast_sync("task_update", {"id": task.id, "project_id": task.project_id, "status": "failed"})
    broadcast_sync("agent_update", {"id": task.agent_id, "status": "idle"})
