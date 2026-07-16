"""Custom CrewAI tools for file operations inside a workspace."""

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from app.services import git_service as git


class FileReadInput(BaseModel):
    path: str = Field(..., description="Relative file path to read, or a directory path to list")


class FileWriteInput(BaseModel):
    path: str = Field(..., description="Relative file path to write")
    content: str = Field(..., description="File content to write")


class FileReadTool(BaseTool):
    name: str = "FileRead"
    description: str = (
        "Read a file in the project workspace. Pass '.' to inspect the project "
        "directory tree before choosing a specific file."
    )
    args_schema: type = FileReadInput

    workspace: str = ""

    def _run(self, path: str) -> str:
        normalized = path.strip().replace("\\", "/")
        if normalized in ("", ".", "./"):
            return self._format_directory_tree(git.list_files(self.workspace))
        return git.read_file(self.workspace, path)

    @staticmethod
    def _format_directory_tree(nodes: list[dict], depth: int = 0, limit: int = 200) -> str:
        """Return a compact, bounded tree for agents that inspect a directory."""
        lines: list[str] = []

        def visit(items: list[dict], level: int) -> None:
            for item in items:
                if len(lines) >= limit:
                    return
                is_dir = item.get("type") in ("dir", "tree")
                suffix = "/" if is_dir else ""
                lines.append(f"{'  ' * level}{item.get('name', '')}{suffix}")
                if is_dir:
                    visit(item.get("children") or [], level + 1)

        visit(nodes, depth)
        if len(lines) >= limit:
            lines.append("... (directory listing truncated)")
        return "\n".join(lines) if lines else "Directory is empty."


class FileWriteTool(BaseTool):
    name: str = "FileWrite"
    description: str = "Write content to a file in the project workspace. Creates parent directories."
    args_schema: type = FileWriteInput

    workspace: str = ""

    def _run(self, path: str, content: str) -> str:
        target = git.write_file(self.workspace, path, content)
        return f"File written: {target}"
