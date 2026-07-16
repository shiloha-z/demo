import unittest
import tempfile
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.messages import list_messages, mark_read, unread_message_count
from app.api.projects import ProjectCreate, create_project, delete_project
from app.api.reviews import VoteRequest, cast_review_vote
from app.api.tasks import resume_task, start_task, stop_task
from app.core.config import settings
from app.services import memory_service as mem
from app.models.models import (
    Agent,
    AgentStatus,
    Base,
    Message,
    Project,
    ProjectMember,
    ProjectRole,
    Review,
    ReviewReviewer,
    ReviewRound,
    ReviewStatus,
    Task,
    TaskStatus,
    User,
)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

        self.owner = User(username="owner", password_hash="x", display_name="Owner")
        self.db.add(self.owner)
        self.db.flush()
        self.project = Project(name="Project", owner_id=self.owner.id, workspace_path="workspace")
        self.db.add(self.project)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.owner.id,
            role=ProjectRole.OWNER,
        ))
        self.agent = Agent(
            creator_id=self.owner.id,
            name="Agent",
            role="code_gen",
            status=AgentStatus.IDLE,
        )
        self.db.add(self.agent)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_task(self, status: TaskStatus) -> Task:
        task = Task(
            agent_id=self.agent.id,
            project_id=self.project.id,
            title="Task",
            status=status,
        )
        self.db.add(task)
        self.db.commit()
        return task


class TaskLifecycleTests(DatabaseTestCase):
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    def test_start_claims_task_and_agent(self, enqueue, _broadcast) -> None:
        task = self.add_task(TaskStatus.PENDING)

        result = start_task(
            self.project.id, task.id, BackgroundTasks(), self.db, self.owner
        )

        self.assertEqual(result.status, TaskStatus.RUNNING.value)
        self.assertEqual(self.db.get(Task, task.id).status, TaskStatus.RUNNING)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.WORKING)
        enqueue.assert_called_once_with(task.id)

    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=False)
    def test_start_rolls_back_state_when_enqueue_fails(self, _enqueue, _broadcast) -> None:
        task = self.add_task(TaskStatus.PENDING)

        with self.assertRaises(HTTPException) as raised:
            start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.get(Task, task.id).status, TaskStatus.PENDING)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.IDLE)

    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.is_agent_run_active", return_value=True)
    def test_soft_pause_keeps_agent_busy_until_runner_returns(self, _active, _broadcast) -> None:
        task = self.add_task(TaskStatus.RUNNING)
        self.agent.status = AgentStatus.WORKING
        self.db.commit()

        stop_task(self.project.id, task.id, self.db, self.owner)

        self.assertEqual(self.db.get(Task, task.id).status, TaskStatus.PAUSED)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.WORKING)

    @patch("app.services.execution_service.is_agent_run_active", return_value=True)
    def test_resume_waits_for_previous_run_to_exit(self, _active) -> None:
        task = self.add_task(TaskStatus.PAUSED)
        self.agent.status = AgentStatus.WORKING
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            resume_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.get(Task, task.id).status, TaskStatus.PAUSED)

    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch("app.services.execution_service.is_agent_run_active", return_value=False)
    def test_resume_transitions_task_before_enqueue(self, _active, enqueue) -> None:
        task = self.add_task(TaskStatus.PAUSED)

        result = resume_task(
            self.project.id, task.id, BackgroundTasks(), self.db, self.owner
        )

        self.assertEqual(result.status, TaskStatus.RUNNING.value)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.WORKING)
        enqueue.assert_called_once_with(task.id, resume=True)


class MessageReadTests(DatabaseTestCase):
    def test_read_receipts_are_per_user(self) -> None:
        other = User(username="other", password_hash="x", display_name="Other")
        message = Message(title="Notice", body="Body")
        self.db.add_all([other, message])
        self.db.commit()

        mark_read(message.id, self.db, self.owner)

        owner_messages = list_messages(None, False, None, 100, self.db, self.owner)
        other_messages = list_messages(None, False, None, 100, self.db, other)
        self.assertTrue(owner_messages[0].read)
        self.assertFalse(other_messages[0].read)
        self.assertEqual(unread_message_count(None, self.db, self.owner)["count"], 0)
        self.assertEqual(unread_message_count(None, self.db, other)["count"], 1)


class ReviewThresholdTests(DatabaseTestCase):
    @patch("app.api.ws.broadcast_sync_to_project")
    def test_owner_vote_does_not_bypass_required_approvals(self, _broadcast) -> None:
        reviewer = User(username="reviewer", password_hash="x", display_name="Reviewer")
        self.db.add(reviewer)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=reviewer.id,
            role=ProjectRole.MEMBER,
        ))
        task = self.add_task(TaskStatus.REVIEWING)
        review = Review(
            task_id=task.id,
            project_id=self.project.id,
            status=ReviewStatus.PENDING,
        )
        self.db.add(review)
        self.db.flush()
        self.db.add(ReviewRound(review_id=review.id, required_approvals=2))
        self.db.add_all([
            ReviewReviewer(review_id=review.id, user_id=self.owner.id),
            ReviewReviewer(review_id=review.id, user_id=reviewer.id),
        ])
        self.db.commit()

        result = cast_review_vote(
            review.id,
            VoteRequest(decision="approve"),
            BackgroundTasks(),
            self.db,
            self.owner,
        )

        self.assertEqual(result["approve_count"], 1)
        self.assertEqual(result["required_approvals"], 2)
        self.assertFalse(result["queued_for_merge"])
        self.assertEqual(self.db.get(Task, task.id).status, TaskStatus.REVIEWING)


class ProjectConsistencyTests(DatabaseTestCase):
    @patch("app.api.projects._broadcast_project_update")
    @patch("app.services.git_service.init_repo")
    def test_create_commits_only_fully_initialized_project(
        self, init_repo, _broadcast
    ) -> None:
        with tempfile.TemporaryDirectory() as root, patch.object(settings, "WORKSPACE_ROOT", root):
            response = create_project(ProjectCreate(name="Ready"), self.db, self.owner)

            self.assertTrue(response.project_id.startswith("PROJ-"))
            self.assertTrue(response.is_member)
            self.assertEqual(self.db.query(Project).filter(Project.name == "Ready").count(), 1)
            self.assertEqual(self.db.query(ProjectMember).count(), 2)
            init_repo.assert_called_once_with(response.workspace_path)

    @patch("app.api.projects._broadcast_project_update")
    @patch("app.services.git_service.init_repo", side_effect=RuntimeError("git failed"))
    def test_create_rolls_back_database_when_workspace_init_fails(
        self, _init_repo, _broadcast
    ) -> None:
        with tempfile.TemporaryDirectory() as root, patch.object(settings, "WORKSPACE_ROOT", root):
            with patch("app.api.projects.logger.exception"):
                with self.assertRaises(HTTPException):
                    create_project(ProjectCreate(name="Broken"), self.db, self.owner)

            self.assertIsNone(self.db.query(Project).filter(Project.name == "Broken").first())
            self.assertEqual(self.db.query(ProjectMember).count(), 1)

    @patch("app.api.projects._broadcast_project_update")
    def test_delete_commits_metadata_before_best_effort_cleanup(
        self, _broadcast
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = f"{root}/workspace"
            import os
            os.makedirs(workspace)
            self.project.workspace_path = workspace
            self.db.commit()

            with (
                patch("app.api.projects.shutil.rmtree", side_effect=OSError("locked")),
                patch("app.api.projects.logger.exception"),
            ):
                result = delete_project(self.project.id, self.db, self.owner)

            self.assertIsNone(self.db.get(Project, self.project.id))
            self.assertIn("warning", result)


class MemoryHierarchyTests(unittest.TestCase):
    def test_agent_memory_uses_a_dedicated_collection_and_cap(self) -> None:
        class FakeCollection:
            def __init__(self) -> None:
                self.added: dict | None = None

            def add(self, **kwargs) -> None:
                self.added = kwargs

        collection = FakeCollection()
        with (
            patch.object(mem, "_get_or_create", return_value=collection) as get_collection,
            patch.object(mem, "_enforce_cap") as enforce_cap,
        ):
            uid = mem.add_agent_memory(42, "Prefer repository conventions", {"type": "lesson"})

        self.assertTrue(uid.startswith("a42_"))
        get_collection.assert_called_once_with("agent_memory_42")
        enforce_cap.assert_called_once_with(collection, mem.AGENT_MEMORY_CAP)
        self.assertEqual(collection.added["documents"], ["Prefer repository conventions"])
        self.assertEqual(collection.added["metadatas"][0]["agent_id"], "42")
        self.assertIn("timestamp", collection.added["metadatas"][0])

    def test_context_and_search_follow_task_agent_project_global_order(self) -> None:
        with (
            patch.object(mem, "mem_ok", return_value=True),
            patch.object(mem, "search_task_memory", return_value=["task context"]),
            patch.object(mem, "search_agent_memory", return_value=["agent lesson"]),
            patch.object(mem, "search_project_memory", return_value=["project convention"]),
            patch.object(mem, "search_global_memory", return_value=["global pattern"]),
        ):
            search_result = mem.search_all(11, 22, "query", agent_id=33)
            context = mem.build_memory_context(22, "query", task_id=11, agent_id=33)

        self.assertEqual(list(search_result), ["task", "agent", "project", "global"])
        self.assertEqual(search_result["agent"], ["agent lesson"])
        self.assertLess(context.index("当前任务上下文"), context.index("Agent 历史经验"))
        self.assertLess(context.index("Agent 历史经验"), context.index("项目历史经验"))
        self.assertLess(context.index("项目历史经验"), context.index("通用模式/经验"))

    def test_invalid_agent_id_does_not_create_or_search_agent_memory(self) -> None:
        with patch.object(mem, "_get_or_create") as get_collection:
            self.assertEqual(mem.add_agent_memory(0, "ignored"), "")
            self.assertEqual(mem.search_agent_memory(0, "query"), [])
        get_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
