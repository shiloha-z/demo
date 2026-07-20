import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from git import Repo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.api.reviews import reject_failed_quality_gate
from app.models.models import (
    Agent,
    Base,
    Project,
    QualityGateRun,
    Review,
    ReviewStatus,
    Task,
    TaskStatus,
    User,
)
from app.services import merge_service
from app.services import git_service
from app.services import quality_gate_service as gates


class QualityGateTests(unittest.TestCase):
    def make_staged_workspace(self, files: dict[str, str]) -> tempfile.TemporaryDirectory:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        repo = Repo.init(root)
        (root / "README.md").write_text("# Test project\n", encoding="utf-8")
        repo.index.add(["README.md"])
        repo.index.commit("initial")
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            repo.index.add([relative])
        repo.close()
        return temp

    def test_required_command_checks_fail_closed_when_unconfigured(self) -> None:
        temp = self.make_staged_workspace({"safe.py": "value = 1\n"})
        self.addCleanup(temp.cleanup)
        with (
            patch.object(settings, "MERGE_TEST_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_UNIT_TEST_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_COVERAGE_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_FORBIDDEN_PATTERNS", ""),
        ):
            results = gates.run_quality_gates(temp.name)

        by_key = {result.key: result for result in results}
        self.assertFalse(by_key["unit_tests"].passed)
        self.assertTrue(by_key["dependency_audit"].passed)
        self.assertFalse(by_key["coverage"].passed)
        self.assertIn("不会将未执行视为通过", by_key["unit_tests"].output)
        self.assertFalse(by_key["unit_tests"].agent_actionable)
        self.assertEqual(by_key["unit_tests"].failure_scope, "platform")
        self.assertFalse(gates.gate_passed(results))

    def test_missing_gate_tool_is_platform_failure(self) -> None:
        temp = self.make_staged_workspace({"safe.py": "value = 1\n"})
        self.addCleanup(temp.cleanup)
        result = gates._run_command(
            temp.name,
            key="unit_tests",
            label="单元测试",
            command="definitely-missing-quality-gate-tool --check",
            required_configuration=True,
        )

        self.assertFalse(result.passed)
        self.assertFalse(result.agent_actionable)
        self.assertEqual(result.failure_scope, "platform")
        self.assertIn("平台管理员", result.output)

    def test_test_artifacts_are_excluded_from_agent_diff(self) -> None:
        temp = self.make_staged_workspace({"safe.py": "value = 1\n"})
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / ".coverage").write_text("generated", encoding="utf-8")
        cache_file = root / ".pytest_cache" / "README.md"
        cache_file.parent.mkdir()
        cache_file.write_text("generated", encoding="utf-8")

        diff = git_service.diff_vs_master(temp.name)

        self.assertIn("safe.py", diff)
        self.assertNotIn(".coverage", diff)
        self.assertNotIn(".pytest_cache", diff)

    def test_builtin_scanners_block_injection_secret_and_bank_rule(self) -> None:
        temp = self.make_staged_workspace({
            "danger.py": (
                "# TODO remove this shortcut\n"
                "password = \"super-secret-value\"\n"
                "cursor.execute(f\"SELECT * FROM users WHERE id={user_id}\")\n"
            ),
        })
        self.addCleanup(temp.cleanup)
        with patch.object(settings, "QUALITY_GATE_FORBIDDEN_PATTERNS", "TODO"):
            results = gates.run_quality_gates(temp.name)

        by_key = {result.key: result for result in results}
        self.assertFalse(by_key["static_analysis"].passed)
        self.assertIn("SQL 注入", by_key["static_analysis"].output)
        self.assertFalse(by_key["secret_scan"].passed)
        self.assertIn("硬编码凭据", by_key["secret_scan"].output)
        self.assertFalse(by_key["bank_policy"].passed)
        self.assertIn("TODO", by_key["bank_policy"].output)

    def test_all_seven_checks_must_pass(self) -> None:
        temp = self.make_staged_workspace({"safe.py": "def add(a, b):\n    return a + b\n"})
        self.addCleanup(temp.cleanup)
        success_command = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        with (
            patch.object(settings, "MERGE_TEST_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_UNIT_TEST_COMMAND", success_command),
            patch.object(settings, "QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND", success_command),
            patch.object(settings, "QUALITY_GATE_COVERAGE_COMMAND", success_command),
            patch.object(settings, "QUALITY_GATE_STYLE_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_STATIC_SCAN_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_SECRET_SCAN_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_BANK_RULE_COMMAND", ""),
            patch.object(settings, "QUALITY_GATE_FORBIDDEN_PATTERNS", ""),
        ):
            results = gates.run_quality_gates(temp.name)

        self.assertEqual(len(results), 7)
        self.assertTrue(all(result.passed for result in results))
        self.assertTrue(gates.gate_passed(results))

    def test_failed_gate_is_persisted_before_human_approval(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        self.addCleanup(engine.dispose)

        user = User(username="owner", password_hash="x")
        session.add(user)
        session.flush()
        project = Project(name="Bank", owner_id=user.id, workspace_path="project-workspace")
        agent = Agent(creator_id=user.id, name="Coder", role="code_gen")
        session.add_all([project, agent])
        session.flush()
        task = Task(
            agent_id=agent.id,
            project_id=project.id,
            title="Transfer API",
            status=TaskStatus.REVIEWING,
            branch_name="task/1",
            worktree_path="task-worktree",
            merge_queued_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.flush()
        review = Review(
            task_id=task.id,
            project_id=project.id,
            status=ReviewStatus.PENDING,
            agent_review_summary="AI review completed",
        )
        session.add(review)
        session.commit()
        failed = gates.GateCheckResult(
            key="unit_tests",
            label="单元测试",
            status="failed",
            required=True,
            output="1 test failed",
            duration_ms=10,
            findings=1,
        )
        with (
            patch.object(gates, "run_quality_gates", return_value=[failed]),
            patch("app.api.ws.broadcast_sync"),
            patch("app.services.audit_service.record"),
        ):
            run = gates.execute_and_persist(
                session,
                task=task,
                review=review,
                workspace="task-worktree",
                commit_hash="a" * 40,
                changed_files=["app.py"],
            )

        self.assertEqual(task.status, TaskStatus.REVIEWING)
        self.assertIn("单元测试", task.merge_error)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.commit_hash, "a" * 40)
        session.close()

    def test_merge_refuses_code_without_a_passed_gate_for_same_commit(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        self.addCleanup(engine.dispose)
        user = User(username="owner2", password_hash="x")
        session.add(user)
        session.flush()
        project = Project(name="Bank", owner_id=user.id, workspace_path="project-workspace")
        agent = Agent(creator_id=user.id, name="Coder", role="code_gen")
        session.add_all([project, agent])
        session.flush()
        task = Task(
            agent_id=agent.id,
            project_id=project.id,
            title="Transfer API",
            status=TaskStatus.MERGE_QUEUED,
            branch_name="task/1",
            worktree_path="task-worktree",
        )
        session.add(task)
        session.flush()
        session.add(Review(
            task_id=task.id,
            project_id=project.id,
            status=ReviewStatus.APPROVED,
            agent_review_summary="AI review completed",
        ))
        session.commit()
        task_id = task.id

        with (
            patch.object(merge_service, "SessionLocal", return_value=session),
            patch.object(merge_service.git, "head_commit", return_value="b" * 40),
            patch.object(merge_service.git, "begin_integration") as begin,
            patch.object(merge_service, "broadcast_sync"),
        ):
            merge_service.integrate_task(task_id)

        blocked = session.get(Task, task_id)
        self.assertEqual(blocked.status, TaskStatus.MERGE_BLOCKED)
        self.assertIn("门禁", blocked.merge_error)
        begin.assert_not_called()
        session.close()

    def test_failed_gate_can_be_returned_to_agent_with_generated_feedback(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        self.addCleanup(engine.dispose)
        owner = User(username="gate-owner", password_hash="x")
        session.add(owner)
        session.flush()
        project = Project(name="Bank", owner_id=owner.id, workspace_path="workspace")
        agent = Agent(creator_id=owner.id, name="Coder", role="code_gen")
        session.add_all([project, agent])
        session.flush()
        task = Task(
            agent_id=agent.id,
            project_id=project.id,
            title="Transfer API",
            status=TaskStatus.REVIEWING,
        )
        session.add(task)
        session.flush()
        review = Review(
            task_id=task.id,
            project_id=project.id,
            status=ReviewStatus.PENDING,
            agent_review_summary="AI review completed",
        )
        session.add(review)
        session.flush()
        session.add(QualityGateRun(
            task_id=task.id,
            review_id=review.id,
            status="failed",
            commit_hash="c" * 40,
            summary="单元测试未通过",
            results_json=json.dumps([{
                "key": "unit_tests",
                "label": "单元测试",
                "status": "failed",
                "output": "test_transfer_limit failed",
            }], ensure_ascii=False),
        ))
        session.commit()

        with (
            patch("app.api.reviews.mem", None),
            patch("app.api.reviews.audit_record"),
            patch("app.api.ws.broadcast_sync"),
            patch("app.services.execution_service.enqueue_agent_run") as enqueue,
            patch("app.services.message_service.push"),
        ):
            reject_failed_quality_gate(review.id, session, owner)

        session.refresh(task)
        session.refresh(review)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertEqual(review.status, ReviewStatus.REJECTED)
        self.assertIn("test_transfer_limit failed", review.human_feedback)
        enqueue.assert_called_once()
        self.assertIn("test_transfer_limit failed", enqueue.call_args.kwargs["feedback"])
        self.assertTrue(enqueue.call_args.kwargs["queue_if_active"])
        session.close()

    def test_platform_gate_failure_cannot_be_returned_to_agent(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        self.addCleanup(engine.dispose)
        owner = User(username="platform-owner", password_hash="x")
        session.add(owner)
        session.flush()
        project = Project(name="Bank", owner_id=owner.id, workspace_path="workspace")
        agent = Agent(creator_id=owner.id, name="Coder", role="code_gen")
        session.add_all([project, agent])
        session.flush()
        task = Task(
            agent_id=agent.id,
            project_id=project.id,
            title="Transfer API",
            status=TaskStatus.REVIEWING,
        )
        session.add(task)
        session.flush()
        review = Review(
            task_id=task.id,
            project_id=project.id,
            status=ReviewStatus.PENDING,
            agent_review_summary="AI review completed",
        )
        session.add(review)
        session.flush()
        session.add(QualityGateRun(
            task_id=task.id,
            review_id=review.id,
            status="failed",
            commit_hash="d" * 40,
            summary="单元测试环境不可用",
            results_json=json.dumps([{
                "key": "unit_tests",
                "label": "单元测试",
                "status": "failed",
                "output": "No module named pytest",
                "failure_scope": "platform",
                "agent_actionable": False,
            }], ensure_ascii=False),
        ))
        session.commit()

        with self.assertRaises(HTTPException) as raised:
            reject_failed_quality_gate(review.id, session, owner)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("Agent 修改代码无法解决", raised.exception.detail)

        session.refresh(task)
        session.refresh(review)
        self.assertEqual(task.status, TaskStatus.REVIEWING)
        self.assertEqual(review.status, ReviewStatus.PENDING)
        session.close()


if __name__ == "__main__":
    unittest.main()
