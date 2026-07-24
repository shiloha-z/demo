"""Regression coverage for sequential integration of concurrent task branches."""

from pathlib import Path
import tempfile
import unittest

from git import Repo

from app.services import git_service as git


class ConcurrentTaskMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.base = root / "project"
        self.task_one = root / "project.worktrees" / "task-1"
        self.task_two = root / "project.worktrees" / "task-2"

        git.init_repo(str(self.base))
        (self.base / "shared.txt").write_text("original\n", encoding="utf-8")
        self.assertTrue(git.commit(str(self.base), "Add shared file"))
        self.assertTrue(
            git.create_task_worktree(str(self.base), str(self.task_one), "task/1")[0]
        )
        self.assertTrue(
            git.create_task_worktree(str(self.base), str(self.task_two), "task/2")[0]
        )

    def tearDown(self) -> None:
        git.remove_task_worktree(str(self.base), str(self.task_one))
        git.remove_task_worktree(str(self.base), str(self.task_two))

    def _commit_task(self, workspace: Path, content: str, message: str) -> str:
        (workspace / "shared.txt").write_text(content, encoding="utf-8")
        commit_hash = git.commit(str(workspace), message)
        self.assertIsNotNone(commit_hash)
        return commit_hash or ""

    def test_second_task_records_base_as_merge_parent_then_integrates(self) -> None:
        """Resolving task 2 must not reproduce the same conflict forever."""
        self._commit_task(self.task_one, "task one\n", "Task one change")
        self._commit_task(self.task_two, "task two\n", "Task two change")

        first = git.begin_integration(str(self.base), "task/1")
        self.assertEqual(first["status"], "ready")
        merged, first_commit = git.finish_integration(
            str(self.base), "Merge task one"
        )
        self.assertTrue(merged, first_commit)

        prepared, files, error = git.prepare_conflict_resolution(
            str(self.task_two), str(self.base), "task/2"
        )
        self.assertTrue(prepared, error)
        self.assertEqual(files, ["shared.txt"])

        # Simulate the resolver retaining both valid changes.
        resolved_content = "task one\ntask two\n"
        resolution_commit = self._commit_task(
            self.task_two, resolved_content, "Resolve task two conflict"
        )
        resolution = Repo(str(self.task_two)).commit(resolution_commit)
        self.assertEqual(
            len(resolution.parents),
            2,
            "Conflict resolution must create a real two-parent merge commit",
        )

        # Once master is a parent, a fresh synchronization cannot rediscover
        # the same conflict and integration into master is clean.
        synced, repeated_conflicts = git.sync_task_branch_with_master(
            str(self.task_two), "task/2"
        )
        self.assertTrue(synced)
        self.assertEqual(repeated_conflicts, [])

        second = git.begin_integration(str(self.base), "task/2")
        self.assertEqual(second["status"], "ready")
        merged, second_commit = git.finish_integration(
            str(self.base), "Merge task two"
        )
        self.assertTrue(merged, second_commit)
        self.assertEqual(
            (self.base / "shared.txt").read_text(encoding="utf-8"),
            resolved_content,
        )
        self.assertEqual(len(Repo(str(self.base)).commit(second_commit).parents), 2)

