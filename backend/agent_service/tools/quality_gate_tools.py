"""CrewAI tool that runs the same deterministic checks used before approval."""

from crewai.tools import BaseTool
from pydantic import BaseModel

from app.services import git_service as git
from app.services import quality_gate_service as quality_gates


class QualityGateInput(BaseModel):
    pass


class QualityGateTool(BaseTool):
    name: str = "DeterministicQualityGate"
    description: str = (
        "Run the project's seven deterministic approval checks on the current "
        "workspace. Use it after writing code and tests. If a code-actionable "
        "check fails, keep modifying files and run this tool again before ending."
    )
    args_schema: type = QualityGateInput

    workspace: str = ""

    def _run(self) -> str:
        changed_files = sorted(git.changed_files_vs_base(self.workspace))
        results = quality_gates.run_quality_gates(
            self.workspace,
            changed_files=changed_files,
        )
        lines = []
        for result in results:
            scope = "可由 Agent 修复" if result.agent_actionable else "需平台管理员处理"
            lines.append(
                f"[{result.status.upper()}] {result.label}（{scope}）\n"
                f"{result.output}"
            )
        return "\n\n".join(lines)
