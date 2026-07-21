"""Custom CrewAI tools for file operations inside a workspace."""

import os
import re

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from app.services import git_service as git

# Characters that are illegal in file/dir names on Windows (and undesirable
# elsewhere). Control characters are covered by the regex as well.
_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_write_path(path: str) -> str:
    """Normalize a model-supplied filepath so it cannot land on disk as an
    odd/garbage path such as ``/347/231/report.md``.

    Models sometimes emit numeric or empty path segments (e.g. when they treat
    section/step ids as directory names). We:
      * collapse back-slashes to forward slashes and drop empty/``.``/``..`` segments
      * replace filesystem-illegal characters with ``_``
      * strip trailing dots/spaces (illegal on Windows)
      * drop pure-numeric intermediate segments (almost never a real directory,
        usually model noise) — the final filename segment is kept even if it is
        numeric so a legitimate ``notes.md``-style file is preserved
    """
    raw = (path or "").strip().replace("\\", "/")
    segments = [s for s in raw.split("/") if s not in ("", ".", "..")]
    cleaned: list[str] = []
    for seg in segments:
        seg = _INVALID_FS_CHARS.sub("_", seg).strip().rstrip(".")
        if not seg:
            continue
        # Drop pure-numeric segments except when it is the final filename part.
        if seg.isdigit() and len(cleaned) > 0:
            continue
        cleaned.append(seg)
    if not cleaned:
        # Everything was dropped — fall back to a safe default, preserving the
        # intended extension if one was present.
        ext = (path or "").rsplit(".", 1)[-1].lower()
        fallback = f"untitled.{ext}" if "." in (path or "") else "untitled"
        return fallback
    return "/".join(cleaned)


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
        safe_path = _sanitize_write_path(path)
        target = git.write_file(self.workspace, safe_path, content)
        return f"File written: {target}"
