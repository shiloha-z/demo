import unittest
from unittest.mock import patch

from app.services import execution_service


class ExecutionServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        with execution_service._lock:
            execution_service._active_agent_tasks.clear()
            execution_service._pending_agent_runs.clear()

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


if __name__ == "__main__":
    unittest.main()
