"""Shared tool implementations used by all runners.

Each runner wraps these in its own tool format:
  - CrewAIRunner: BaseTool subclasses
  - ClaudeCodeRunner: @tool decorated async functions
  - OpenCodeRunner: registered callables
"""

from app.services import git_service as git
from app.services import memory_service as mem


def read_file(workspace: str, path: str) -> str:
    """Read a file from the workspace (master branch)."""
    return git.read_file(workspace, path)


def write_file(workspace: str, path: str, content: str) -> str:
    """Write content to a file in the workspace."""
    target = git.write_file(workspace, path, content)
    return f"File written: {target}"


def get_diff(workspace: str) -> str:
    """Get staged + unstaged git diff in the workspace."""
    diff = git.get_diff(workspace)
    return diff if diff else "No changes detected."


def search_memory(task_id: int, project_id: int, query: str, agent_id: int = 0) -> str:
    """Search across task, agent, project, and global memory layers."""
    try:
        results = mem.search_all(task_id, project_id, query, n_results=5, agent_id=agent_id)
        if not results:
            return "No relevant memories found."
        lines = []
        for layer, docs in results.items():
            if docs:
                lines.append(f"--- {layer} ---")
                for doc in docs:
                    lines.append(f"  • {doc}")
        return "\n".join(lines)
    except Exception as e:
        return f"Memory search failed: {e}"


def record_memory(task_id: int, project_id: int, scope: str, content: str, agent_id: int = 0) -> str:
    """Record an insight to task, agent, project, or global memory."""
    try:
        metadata = {"task_id": str(task_id), "project_id": str(project_id), "agent_id": str(agent_id)}
        if scope == "task":
            mem.add_task_memory(task_id, content, metadata)
        elif scope == "agent":
            if not mem.add_agent_memory(agent_id, content, metadata):
                return "Agent memory unavailable."
        elif scope == "project":
            mem.add_project_memory(project_id, content, metadata)
        elif scope == "global":
            mem.add_global_memory(content, metadata)
        else:
            return f"Unknown scope: {scope}. Use 'task', 'agent', 'project', or 'global'."
        return f"Recorded to {scope} memory."
    except Exception as e:
        return f"Memory record failed: {e}"


def list_files(workspace: str, subpath: str = "") -> str:
    """List files in the workspace."""
    try:
        entries = git.list_files(workspace, subpath)
        if not entries:
            return "(empty directory)"
        lines = []
        for e in entries:
            prefix = "📁" if e.get("type") == "dir" else "📄"
            lines.append(f"  {prefix} {e['name']}")
        return "\n".join(lines)
    except Exception as e:
        return f"List failed: {e}"
