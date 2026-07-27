import unittest
from unittest.mock import MagicMock, patch

from app.services import execution_service


class ExecutionServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        with execution_service._lock:
            execution_service._active_agent_tasks.clear()
            execution_service._pending_agent_runs.clear()
            execution_service._active_merge_projects.clear()

    def test_revision_is_queued_when_previous_run_is_still_finishing(self) -> None:
        task_id = 77
        with execution_service._lock:
            execution_service._active_agent_tasks.add(task_id)

        with patch.object(execution_service._agent_executor, "submit") as submit:
            queued = execution_service.enqueue_agent_run(
                task_id,
                feedback="fix failed tests",
                queue_if_active=True,
            )
            self.assertTrue(queued)
            submit.assert_not_called()

            with patch("app.services.agent_runner.run_agent_pipeline"):
                execution_service._run_agent(task_id, "first run", False, False)

            submit.assert_called_once_with(
                execution_service._run_agent,
                task_id,
                "fix failed tests",
                False,
                False,
            )

    def test_merge_worker_reclaims_project_when_work_arrives_during_exit(self) -> None:
        project_id = 9
        with execution_service._lock:
            execution_service._active_merge_projects.add(project_id)

        # First lookup sees no work. The under-lock exit recheck then sees task
        # 81, and the next loop consumes it. Final two lookups release cleanly.
        lookups = [None, 81, 81, None, None]
        with (
            patch.object(
                execution_service,
                "_next_queued_merge_task_id",
                side_effect=lookups,
            ),
            patch("app.services.merge_service.integrate_task") as integrate,
        ):
            execution_service._drain_project_merges(project_id)

        integrate.assert_called_once_with(81)
        with execution_service._lock:
            self.assertNotIn(
                project_id,
                execution_service._active_merge_projects,
            )

    def test_enqueue_merge_releases_project_when_executor_is_shutting_down(self) -> None:
        task = type("TaskRow", (), {"project_id": 12})()
        db = MagicMock()
        db.get.return_value = task
        with (
            patch.object(execution_service, "SessionLocal", return_value=db),
            patch.object(
                execution_service._merge_executor,
                "submit",
                side_effect=RuntimeError("shutdown"),
            ),
        ):
            self.assertFalse(execution_service.enqueue_merge(77))

        with execution_service._lock:
            self.assertNotIn(12, execution_service._active_merge_projects)


if __name__ == "__main__":
    unittest.main()
