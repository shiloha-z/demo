"""Abstract base for agent execution backends.

The orchestrator (agent_runner.py) handles:
  - Status transitions (PENDING → RUNNING → REVIEWING / FAILED)
  - Git branch management, commit, diff generation, Review record creation
  - WebSocket broadcasting

The runner handles:
  - Agent execution (CrewAI pipeline, Claude Code session, OpenCode session)
  - Tool provisioning (file read/write, git diff, memory search/record)
  - Progress and stage reporting via callbacks
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections.abc import Callable


@dataclass
class RunResult:
    """Unified result from any backend runner."""
    summary: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# Progress callback: (message: str, step: str) → None
ProgressCallback = Callable[[str, str], None]

# Stage callback: (stage_key: str, status: str) → None
# stage_key: "code_gen" | "reviewer" | "security" | "summarizer"
# status: "waiting" | "running" | "done" | "error"
StageCallback = Callable[[str, str], None]


class BaseRunner(ABC):
    """Abstract base for agent execution backends."""

    @abstractmethod
    def run(
        self,
        task_description: str,
        workspace: str,
        model_name: str,
        task_id: int,
        project_id: int,
        *,
        on_progress: ProgressCallback | None = None,
        on_stage: StageCallback | None = None,
    ) -> RunResult:
        """Execute the agent pipeline and return a result.

        Args:
            task_description: The user's task description / requirements.
            workspace: Absolute path to the project workspace.
            model_name: LLM model identifier (e.g. "deepseek-chat", "claude-sonnet-4-20250514").
            task_id: Task ID for progress reporting.
            project_id: Project ID for progress reporting.
            on_progress: Optional callback for step-level progress messages.
            on_stage: Optional callback for pipeline stage transitions.

        Returns:
            RunResult with summary text (Markdown report) or error message.
        """
        ...
