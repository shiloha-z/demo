"""Custom CrewAI tools for file operations inside a workspace."""

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from app.services import git_service as git


class FileReadInput(BaseModel):
    path: str = Field(..., description="Relative file path to read")


class FileWriteInput(BaseModel):
    path: str = Field(..., description="Relative file path to write")
    content: str = Field(..., description="File content to write")


class FileReadTool(BaseTool):
    name: str = "FileRead"
    description: str = "Read the contents of a file in the project workspace."
    args_schema: type = FileReadInput

    workspace: str = ""

    def _run(self, path: str) -> str:
        return git.read_file(self.workspace, path)


class FileWriteTool(BaseTool):
    name: str = "FileWrite"
    description: str = "Write content to a file in the project workspace. Creates parent directories."
    args_schema: type = FileWriteInput

    workspace: str = ""

    def _run(self, path: str, content: str) -> str:
        target = git.write_file(self.workspace, path, content)
        return f"File written: {target}"
