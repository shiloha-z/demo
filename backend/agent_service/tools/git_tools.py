"""Custom CrewAI tool for git operations inside a workspace."""

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from app.services import git_service as git


class GitDiffInput(BaseModel):
    pass  # No input needed — diff is computed for the whole workspace


class GitDiffTool(BaseTool):
    name: str = "GitDiff"
    description: str = (
        "Get the current git diff showing all staged and unstaged changes in the "
        "workspace. Use this to see what files have changed."
    )
    args_schema: type = GitDiffInput

    workspace: str = ""

    def _run(self) -> str:
        # Agent-created files are usually untracked until the orchestration
        # layer commits the task. `get_diff()` omits those files, which made
        # a reviewer incorrectly conclude that a freshly generated file did
        # not exist. This stages only the task worktree and diffs it against
        # its base branch, so new files are visible to every review Agent.
        diff = git.diff_vs_master(self.workspace)
        return diff if diff else "No changes detected."
