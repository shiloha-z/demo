"""Integration tests covering the four core business flows.

Flow 1: Create → Start → Review → Approve → Merge (happy path)
Flow 2: Create → Start → Review → Reject → Re-execute
Flow 3: Merge conflict → Auto-resolve → Re-vote
Flow 4: Version rollback
"""

import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.tasks import TaskCreate, create_task, start_task
from app.api.reviews import (
    VoteRequest,
    cast_review_vote,
    reject_review,
    RejectRequest,
)
from app.services import merge_service
from app.api.versions import rollback_version
from app.core.config import settings
from app.models.models import (
    Agent,
    AgentStatus,
    Base,
    Project,
    ProjectMember,
    ProjectRole,
    QualityGateRun,
    Review,
    ReviewReviewer,
    ReviewRound,
    ReviewStatus,
    ReviewVote,
    Task,
    TaskStatus,
    User,
    Version,
)


class DatabaseTestCase(unittest.TestCase):
    """Base class providing an isolated in-memory SQLite database per test."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

        # ── Owner ──────────────────────────────────────────────────
        self.owner = User(username="owner", password_hash="x", display_name="Owner")
        self.db.add(self.owner)
        self.db.flush()

        # ── Project ────────────────────────────────────────────────
        self.project = Project(
            name="TestProject",
            owner_id=self.owner.id,
            workspace_path="workspace",
        )
        self.db.add(self.project)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.owner.id,
            role=ProjectRole.OWNER,
        ))

        # ── Agent ──────────────────────────────────────────────────
        self.agent = Agent(
            creator_id=self.owner.id,
            name="Coder",
            role="code_gen",
            status=AgentStatus.IDLE,
        )
        self.db.add(self.agent)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    # ── Helpers ───────────────────────────────────────────────────────

    def add_task(self, status: TaskStatus = TaskStatus.PENDING) -> Task:
        task = Task(
            agent_id=self.agent.id,
            project_id=self.project.id,
            title="Test Task",
            description="Implement feature X",
            status=status,
            approval_percent=50,
        )
        self.db.add(task)
        self.db.commit()
        return task

    def add_reviewer(self, username: str) -> User:
        """Create a second project member who can vote."""
        user = User(username=username, password_hash="x", display_name=username.title())
        self.db.add(user)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=user.id,
            role=ProjectRole.MEMBER,
        ))
        self.db.commit()
        return user

    def simulate_pipeline_complete(
        self,
        task: Task,
        commit_hash: str = "a" * 40,
    ) -> Review:
        """Simulate what _run_agent_pipeline does after the agent finishes.

        Creates Review, ReviewRound, ReviewReviewers, QualityGateRun(passed),
        and transitions task → REVIEWING, agent → DONE.
        """
        # Worktree path is required downstream
        self.temp_worktree = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_worktree.cleanup)
        task.worktree_path = self.temp_worktree.name
        task.branch_name = f"task/{task.id}"
        task.status = TaskStatus.REVIEWING
        self.agent.status = AgentStatus.DONE
        self.db.flush()

        review = Review(
            task_id=task.id,
            project_id=self.project.id,
            diff_content="+def new_feature():\n+    return True\n",
            agent_review_summary="## Code Review\n\nLGTM. No issues found.",
            status=ReviewStatus.PENDING,
        )
        self.db.add(review)
        self.db.flush()

        # Voting round: all project members
        member_ids = [
            row[0] for row in self.db.query(ProjectMember.user_id).filter(
                ProjectMember.project_id == self.project.id
            ).all()
        ]
        round_ = ReviewRound(
            review_id=review.id,
            required_approvals=max(1, min(2, len(member_ids))),
        )
        self.db.add(round_)
        for uid in member_ids:
            self.db.add(ReviewReviewer(review_id=review.id, user_id=uid))

        # Synthesise a passed quality gate
        self.db.add(QualityGateRun(
            task_id=task.id,
            review_id=review.id,
            status="passed",
            commit_hash=commit_hash,
            results_json="[]",
        ))
        self.db.commit()
        return review


# ═══════════════════════════════════════════════════════════════════════
# Flow 1: Happy Path — Create → Start → Review → Approve → Merge
# ═══════════════════════════════════════════════════════════════════════

class HappyPathTests(DatabaseTestCase):
    """End-to-end happy path: from task creation through merge approval."""

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_full_happy_path_create_to_merge(self, enqueue, _ws, _wsp) -> None:
        """Task flows from PENDING → RUNNING → REVIEWING → MERGE_QUEUED → APPROVED."""
        # ── Step 1: Create task ────────────────────────────────────
        task_resp = create_task(
            self.project.id,
            TaskCreate(title="Add transfer API", description="Build REST endpoint", agent_id=self.agent.id),
            BackgroundTasks(),
            self.db,
            self.owner,
        )
        self.assertEqual(task_resp.status, "pending")
        task = self.db.get(Task, task_resp.id)
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.IDLE)

        # ── Step 2: Start task ─────────────────────────────────────
        # broadcast_sync and enqueue_agent_run already mocked at method level
        start_resp = start_task(
            self.project.id, task.id, BackgroundTasks(), self.db, self.owner
        )
        self.assertEqual(start_resp.status, "running")
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertEqual(self.db.get(Agent, self.agent.id).status, AgentStatus.WORKING)
        enqueue.assert_called_with(task.id)

        # ── Step 3: Simulate pipeline completion ────────────────────
        reviewer = self.add_reviewer("reviewer1")
        review = self.simulate_pipeline_complete(task)
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.REVIEWING)
        self.assertEqual(review.status, ReviewStatus.PENDING)

        # Verify voting infrastructure
        rround = self.db.query(ReviewRound).filter(ReviewRound.review_id == review.id).first()
        self.assertIsNotNone(rround)
        self.assertEqual(rround.required_approvals, 2)
        reviewers = self.db.query(ReviewReviewer).filter(
            ReviewReviewer.review_id == review.id
        ).all()
        self.assertEqual(len(reviewers), 2)

        # ── Step 4: First approve vote (owner) — quorum NOT met ────
        with patch("app.services.execution_service.enqueue_merge"):
            result1 = cast_review_vote(
                review.id,
                VoteRequest(decision="approve", comment="Looks good"),
                BackgroundTasks(),
                self.db,
                self.owner,
            )
        self.assertEqual(result1["approve_count"], 1)
        self.assertEqual(result1["required_approvals"], 2)
        self.assertFalse(result1["queued_for_merge"])
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.REVIEWING)

        # ── Step 5: Second approve vote (reviewer) — quorum MET ────
        with patch("app.services.execution_service.enqueue_merge"):
            result2 = cast_review_vote(
                review.id,
                VoteRequest(decision="approve", comment="Approved"),
                BackgroundTasks(),
                self.db,
                reviewer,
            )
        self.assertEqual(result2["approve_count"], 2)
        self.assertTrue(result2["queued_for_merge"])
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.MERGE_QUEUED)
        self.db.refresh(review)
        self.assertEqual(review.status, ReviewStatus.APPROVED)

        # ── Step 6: Merge integration ───────────────────────────────
        integ_session = self.Session()
        with (
            patch.object(merge_service, "SessionLocal", return_value=integ_session),
            patch.object(merge_service, "broadcast_sync"),
            patch.object(settings, "QUALITY_GATE_ENABLED", False),
        ):
            integ_task = integ_session.get(Task, task.id)
            self.assertIsNotNone(integ_task)

            with (
                patch.object(merge_service.git, "head_commit", return_value="a" * 40),
                patch.object(merge_service.git, "begin_integration", return_value={"status": "ready"}),
                patch.object(merge_service.git, "finish_integration", return_value=(True, "abc123def456")),
                patch.object(merge_service.git, "remove_task_worktree", return_value=True),
                patch.object(merge_service.git, "delete_branch", return_value=True),
                patch.object(merge_service.git, "default_task_worktree_path", return_value=task.worktree_path),
            ):
                merge_service.integrate_task(task.id)

        # Verify merge outcome (re-query after integrate_task closes the session)
        integ_task = integ_session.get(Task, task.id)
        self.assertEqual(integ_task.status, TaskStatus.APPROVED)
        self.assertIsNotNone(integ_task.completed_at)

        version = integ_session.query(Version).filter(
            Version.project_id == self.project.id
        ).first()
        self.assertIsNotNone(version)
        self.assertEqual(version.commit_hash, "abc123def456")
        integ_session.close()

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_approval_requires_quorum(self, enqueue, _ws, _wsp) -> None:
        """A single approve vote must not merge when required_approvals > 1."""
        self.add_reviewer("r1")
        self.add_reviewer("r2")
        task = self.add_task(TaskStatus.PENDING)
        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)
        review = self.simulate_pipeline_complete(task)

        with patch("app.services.execution_service.enqueue_merge"):
            result = cast_review_vote(
                review.id,
                VoteRequest(decision="approve"),
                BackgroundTasks(),
                self.db,
                self.owner,
            )
        self.assertEqual(result["approve_count"], 1)
        self.assertFalse(result["queued_for_merge"])

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_vote_by_non_reviewer_is_rejected(self, _ws, _wsp) -> None:
        """A user not assigned as a reviewer cannot vote."""
        outsider = User(username="outsider", password_hash="x", display_name="Outsider")
        self.db.add(outsider)
        self.db.flush()
        task = self.add_task(TaskStatus.PENDING)
        review = self.simulate_pipeline_complete(task)

        with self.assertRaises(HTTPException) as raised:
            cast_review_vote(
                review.id,
                VoteRequest(decision="approve"),
                BackgroundTasks(),
                self.db,
                outsider,
            )
        self.assertEqual(raised.exception.status_code, 403)

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_merge")
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_vote_by_member_not_assigned_is_rejected(self, _em, _ws, _wsp) -> None:
        """A project member who is NOT in ReviewReviewer cannot vote."""
        member = self.add_reviewer("memberX")
        task = self.add_task(TaskStatus.PENDING)
        review = self.simulate_pipeline_complete(task)
        # Remove member from ReviewReviewer
        self.db.query(ReviewReviewer).filter(
            ReviewReviewer.review_id == review.id,
            ReviewReviewer.user_id == member.id,
        ).delete()
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            cast_review_vote(
                review.id,
                VoteRequest(decision="approve"),
                BackgroundTasks(),
                self.db,
                member,
            )
        self.assertEqual(raised.exception.status_code, 403)


# ═══════════════════════════════════════════════════════════════════════
# Flow 2: Reject → Agent Re-execute
# ═══════════════════════════════════════════════════════════════════════

class RejectReexecutionTests(DatabaseTestCase):
    """Rejection with veto triggers agent re-run with feedback."""

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_reject_with_veto_triggers_agent_rerun(self, enqueue, _ws, _wsp) -> None:
        """Veto-on-reject sends task back to RUNNING with feedback for agent."""
        self.add_reviewer("reviewer1")
        task = self.add_task(TaskStatus.PENDING)

        # Start task (broadcast_sync and enqueue_agent_run already mocked)
        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)

        # Simulate pipeline completion
        review = self.simulate_pipeline_complete(task)

        # Reset enqueue_agent_run call count (was called by start_task)
        enqueue.reset_mock()

        # Owner casts a REJECT vote (veto triggers immediately)
        with patch("app.services.execution_service.enqueue_merge"):
            result = cast_review_vote(
                review.id,
                VoteRequest(decision="reject", comment="银行卡号未脱敏，必须修改"),
                BackgroundTasks(),
                self.db,
                self.owner,
            )

        # Verify vote result
        self.assertEqual(result["reject_count"], 1)

        # Verify review is rejected
        self.db.refresh(review)
        self.assertEqual(review.status, ReviewStatus.REJECTED)
        self.assertIn("银行卡号未脱敏", review.human_feedback)

        # Verify task is sent back to RUNNING
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNone(task.completed_at)

        # Verify agent is WORKING again
        self.db.refresh(self.agent)
        self.assertEqual(self.agent.status, AgentStatus.WORKING)

        # Verify agent re-run was enqueued with feedback
        enqueue.assert_called_once()
        call_kwargs = enqueue.call_args.kwargs
        self.assertIn("银行卡号未脱敏", call_kwargs.get("feedback", ""))

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_reject_requires_comment(self, _ws, _wsp) -> None:
        """Rejection vote without comment is rejected with 400."""
        task = self.add_task(TaskStatus.PENDING)
        review = self.simulate_pipeline_complete(task)

        with self.assertRaises(HTTPException) as raised:
            cast_review_vote(
                review.id,
                VoteRequest(decision="reject", comment=""),
                BackgroundTasks(),
                self.db,
                self.owner,
            )
        self.assertEqual(raised.exception.status_code, 400)

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_admin_reject_endpoint(self, enqueue, _ws, _wsp) -> None:
        """Admin reject_review() endpoint works the same as vote-reject."""
        task = self.add_task(TaskStatus.PENDING)
        review = self.simulate_pipeline_complete(task)

        result = reject_review(
            review.id,
            RejectRequest(feedback="Security issue: SQL injection risk"),
            BackgroundTasks(),
            self.db,
            self.owner,
        )

        self.assertEqual(result["message"], "Rejected — agent will re-run with feedback")
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.db.refresh(review)
        self.assertEqual(review.status, ReviewStatus.REJECTED)
        self.assertIn("SQL injection", review.human_feedback)
        enqueue.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# Flow 3: Merge Conflict → Auto-resolve → Re-vote
# ═══════════════════════════════════════════════════════════════════════

class MergeConflictTests(DatabaseTestCase):
    """Merge conflicts are handed off to agent for resolution, then re-reviewed."""

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_merge_conflict_triggers_resolution(self, enqueue, _ws, _wsp) -> None:
        """When merge conflicts, task goes to CONFLICT_RESOLUTION with agent feedback."""
        reviewer = self.add_reviewer("r1")
        task = self.add_task(TaskStatus.PENDING)

        # Start task
        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)

        # Pipeline complete
        review = self.simulate_pipeline_complete(task)

        # Approve → MERGE_QUEUED
        with patch("app.services.execution_service.enqueue_merge"):
            cast_review_vote(
                review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, self.owner
            )
            cast_review_vote(
                review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, reviewer
            )
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.MERGE_QUEUED)
        self.db.refresh(review)
        self.assertEqual(review.status, ReviewStatus.APPROVED)

        # Reset enqueue mock (called by start_task)
        enqueue.reset_mock()

        # ── Simulate merge conflict ─────────────────────────────────
        integ_session = self.Session()
        with (
            patch.object(merge_service, "SessionLocal", return_value=integ_session),
            patch.object(merge_service, "broadcast_sync"),
            patch.object(settings, "QUALITY_GATE_ENABLED", False),
        ):
            integ_task = integ_session.get(Task, task.id)
            with (
                patch.object(merge_service.git, "head_commit", return_value="a" * 40),
                patch.object(merge_service.git, "begin_integration", return_value={
                    "status": "conflict",
                    "files": ["app.py", "models.py"],
                }),
                patch.object(merge_service.git, "prepare_conflict_resolution", return_value=(
                    True, ["app.py", "models.py"], ""
                )),
                patch.object(merge_service.git, "abort_integration"),
                patch.object(merge_service.git, "default_task_worktree_path", return_value=task.worktree_path),
            ):
                merge_service.integrate_task(task.id)

        # Verify conflict resolution state (re-query after integrate_task closes the session)
        integ_task = integ_session.get(Task, task.id)
        self.assertEqual(integ_task.status, TaskStatus.CONFLICT_RESOLUTION)
        self.assertIn("app.py", integ_task.merge_error)
        self.assertIn("models.py", integ_task.merge_error)

        # Verify agent was enqueued for conflict resolution
        enqueue.assert_called_once()
        call_kwargs = enqueue.call_args.kwargs
        self.assertTrue(call_kwargs.get("conflict_resolution"))
        self.assertIn("app.py", call_kwargs.get("feedback", ""))
        self.assertIn("models.py", call_kwargs.get("feedback", ""))
        integ_session.close()

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_clean_merge_retries_without_agent(self, _enq, _ws, _wsp) -> None:
        """When base advanced but merges cleanly, retry integration without agent."""
        reviewer = self.add_reviewer("r1")
        task = self.add_task(TaskStatus.PENDING)

        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)
        review = self.simulate_pipeline_complete(task)

        with patch("app.services.execution_service.enqueue_merge"):
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, self.owner)
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, reviewer)
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.MERGE_QUEUED)

        # Conflict initially, but prepare_conflict_resolution returns no files → clean merge
        integ_session = self.Session()
        with (
            patch.object(merge_service, "SessionLocal", return_value=integ_session),
            patch.object(merge_service, "broadcast_sync"),
            patch.object(settings, "QUALITY_GATE_ENABLED", False),
        ):
            integ_task = integ_session.get(Task, task.id)
            with (
                patch.object(merge_service.git, "head_commit", return_value="a" * 40),
                patch.object(merge_service.git, "begin_integration", return_value={
                    "status": "conflict", "files": ["app.py"],
                }),
                patch.object(merge_service.git, "prepare_conflict_resolution", return_value=(
                    True, [], ""
                )),
                patch.object(merge_service.git, "abort_integration"),
                patch.object(merge_service.git, "default_task_worktree_path", return_value=task.worktree_path),
            ):
                merge_service.integrate_task(task.id)

        # Should go back to MERGE_QUEUED for retry (not CONFLICT_RESOLUTION)
        integ_task = integ_session.get(Task, task.id)
        self.assertEqual(integ_task.status, TaskStatus.MERGE_QUEUED)
        integ_session.close()


# ═══════════════════════════════════════════════════════════════════════
# Flow 4: Version Rollback
# ═══════════════════════════════════════════════════════════════════════

class VersionRollbackTests(DatabaseTestCase):
    """Version history and rollback after a successful merge."""

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_rollback_creates_new_version(self, enqueue, _ws, _wsp) -> None:
        """Rollback to a past version creates an auditable new Version record."""
        # ── Complete a happy-path merge to get a Version ────────────
        reviewer = self.add_reviewer("r1")
        task = self.add_task(TaskStatus.PENDING)

        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)
        review = self.simulate_pipeline_complete(task)

        with patch("app.services.execution_service.enqueue_merge"):
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, self.owner)
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, reviewer)

        integ_session = self.Session()
        with (
            patch.object(merge_service, "SessionLocal", return_value=integ_session),
            patch.object(merge_service, "broadcast_sync"),
            patch.object(settings, "QUALITY_GATE_ENABLED", False),
        ):
            integ_task = integ_session.get(Task, task.id)
            with (
                patch.object(merge_service.git, "head_commit", return_value="a" * 40),
                patch.object(merge_service.git, "begin_integration", return_value={"status": "ready"}),
                patch.object(merge_service.git, "finish_integration", return_value=(True, "abc123def456")),
                patch.object(merge_service.git, "remove_task_worktree", return_value=True),
                patch.object(merge_service.git, "delete_branch", return_value=True),
                patch.object(merge_service.git, "default_task_worktree_path", return_value=task.worktree_path),
            ):
                merge_service.integrate_task(task.id)
        integ_session.close()

        # Verify initial version exists
        version1 = self.db.query(Version).filter(
            Version.project_id == self.project.id
        ).first()
        self.assertIsNotNone(version1)
        self.assertEqual(version1.commit_hash, "abc123def456")

        # ── Rollback ─────────────────────────────────────────────────
        with patch("app.api.ws.broadcast_sync"):
            from app.services import git_service
            with patch.object(git_service, "rollback", return_value="def789abc123"):
                result = rollback_version(
                    self.project.id,
                    version1.id,
                    self.db,
                    self.owner,
                )

        self.assertTrue(result.success)

        # Verify a new Version was created for the rollback
        versions = self.db.query(Version).filter(
            Version.project_id == self.project.id
        ).order_by(Version.id.desc()).all()
        self.assertGreaterEqual(len(versions), 2)
        self.assertEqual(versions[0].commit_hash, "def789abc123")

    @patch("app.api.ws.broadcast_sync_to_project")
    @patch("app.api.ws.broadcast_sync")
    @patch("app.services.execution_service.enqueue_agent_run", return_value=True)
    @patch.object(settings, "QUALITY_GATE_ENABLED", False)
    def test_rollback_noop_when_already_on_version(self, enqueue, _ws, _wsp) -> None:
        """Rollback to the current version does not create a duplicate."""
        reviewer = self.add_reviewer("r1")
        task = self.add_task(TaskStatus.PENDING)

        start_task(self.project.id, task.id, BackgroundTasks(), self.db, self.owner)
        review = self.simulate_pipeline_complete(task)

        with patch("app.services.execution_service.enqueue_merge"):
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, self.owner)
            cast_review_vote(review.id, VoteRequest(decision="approve"), BackgroundTasks(), self.db, reviewer)

        integ_session = self.Session()
        with (
            patch.object(merge_service, "SessionLocal", return_value=integ_session),
            patch.object(merge_service, "broadcast_sync"),
            patch.object(settings, "QUALITY_GATE_ENABLED", False),
        ):
            integ_task = integ_session.get(Task, task.id)
            with (
                patch.object(merge_service.git, "head_commit", return_value="a" * 40),
                patch.object(merge_service.git, "begin_integration", return_value={"status": "ready"}),
                patch.object(merge_service.git, "finish_integration", return_value=(True, "hash123")),
                patch.object(merge_service.git, "remove_task_worktree", return_value=True),
                patch.object(merge_service.git, "delete_branch", return_value=True),
                patch.object(merge_service.git, "default_task_worktree_path", return_value=task.worktree_path),
            ):
                merge_service.integrate_task(task.id)
        integ_session.close()

        version_count_before = self.db.query(Version).filter(
            Version.project_id == self.project.id
        ).count()

        version = self.db.query(Version).first()
        # git.rollback returns the SAME hash → no new commit → no new Version
        with patch("app.api.ws.broadcast_sync"):
            from app.services import git_service
            with patch.object(git_service, "rollback", return_value="hash123"):
                result = rollback_version(
                    self.project.id,
                    version.id,
                    self.db,
                    self.owner,
                )

        self.assertTrue(result.success)
        version_count_after = self.db.query(Version).filter(
            Version.project_id == self.project.id
        ).count()
        self.assertEqual(version_count_before, version_count_after)


if __name__ == "__main__":
    unittest.main()
