from pathlib import Path
import tempfile

from app.services import git_service as git


def test_review_evidence_tracks_snapshot_and_worktree_independently() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "project"
        workspace = Path(tmp) / "project.worktrees" / "task-1"
        git.init_repo(str(base))
        created, error = git.create_task_worktree(
            str(base),
            str(workspace),
            "task/1",
        )
        assert created, error

        try:
            readme = workspace / "README.md"
            readme.write_text("# Example\n\n## Usage\nRun it.\n", encoding="utf-8")

            staged = git.build_review_evidence(str(workspace))
            item = next(
                entry for entry in staged["files"]
                if entry["path"] == "README.md"
            )
            assert staged["source"] == "index"
            assert item["line_count"] == 4
            assert item["placeholder"] is False
            assert item["worktree_matches_snapshot"] is True
            assert len(item["sha256"]) == 64
            assert len(item["git_blob"]) == 40

            commit_hash = git.commit(str(workspace), "Write documentation")
            assert commit_hash
            committed = git.build_review_evidence(str(workspace), commit_hash)
            committed_item = next(
                entry for entry in committed["files"]
                if entry["path"] == "README.md"
            )
            assert committed["source"] == "commit"
            assert committed_item["sha256"] == item["sha256"]
            assert committed_item["worktree_matches_snapshot"] is True

            readme.write_text("# Project Workspace\n", encoding="utf-8")
            changed_worktree = git.build_review_evidence(str(workspace), commit_hash)
            changed_item = next(
                entry for entry in changed_worktree["files"]
                if entry["path"] == "README.md"
            )
            assert changed_item["line_count"] == 4
            assert changed_item["placeholder"] is False
            assert changed_item["worktree_matches_snapshot"] is False
        finally:
            git.remove_task_worktree(str(base), str(workspace))
