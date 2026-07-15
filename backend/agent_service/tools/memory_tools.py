"""CrewAI tools for the ChromaDB 3-layer memory system.

Each agent in the pipeline can:
  - Search memories (task → project → global) before acting
  - Record observations and decisions after acting

Tools are workspace-scoped so they know which task/project they belong to.
"""

from crewai.tools import BaseTool


class MemorySearchTool(BaseTool):
    """Search all three memory layers for relevant context.

    Use this BEFORE making changes to understand:
      - What patterns worked or failed before (global/project memory)
      - What was discussed earlier in this task (task memory)
    """

    name: str = "MemorySearch"
    description: str = (
        "Search the 3-layer memory system for relevant knowledge. "
        "Returns results from task memory (this run), project memory "
        "(across tasks in this project), and global memory (all projects). "
        "Input: a search query string describing what you want to know."
    )

    task_id: int = 0
    project_id: int = 0

    def _run(self, query: str) -> str:
        from app.services.memory_service import search_all

        results = search_all(self.task_id, self.project_id, query, n_results=3)

        lines: list[str] = []
        for layer, docs in results.items():
            label = {"task": "📋 任务记忆", "project": "📁 项目记忆", "global": "🌐 全局记忆"}.get(layer, layer)
            if docs:
                lines.append(f"\n### {label}")
                for i, doc in enumerate(docs, 1):
                    lines.append(f"{i}. {doc}")
            else:
                lines.append(f"\n### {label}\n(无结果)")

        return "\n".join(lines).strip() if lines else "未找到相关记忆。"


class MemoryRecordTool(BaseTool):
    """Record a new observation or decision into project & global memory.

    Use this AFTER completing a step to share what you learned:
      - task-level: automatically recorded by the pipeline
      - project-level: patterns specific to this project
      - global-level: general lessons for any project
    """

    name: str = "MemoryRecord"
    description: str = (
        "Record an insight or lesson learned. "
        "Input format: 'SCOPE: content' where SCOPE is 'project' or 'global'. "
        "Example: 'project: SQLite connection pooling should use check_same_thread=False' "
        "Example: 'global: Always sanitize file paths before writing to disk'"
    )

    task_id: int = 0
    project_id: int = 0

    def _run(self, input_str: str) -> str:
        from app.services.memory_service import add_project_memory, add_global_memory

        scope, content = "project", input_str
        if ":" in input_str:
            parts = input_str.split(":", 1)
            if parts[0].strip().lower() in ("project", "global"):
                scope = parts[0].strip().lower()
                content = parts[1].strip()

        if scope == "global":
            uid = add_global_memory(content)
            return f"✅ 已记录到全局记忆 [{uid}]"
        else:
            uid = add_project_memory(self.project_id, content)
            return f"✅ 已记录到项目记忆 [{uid}]"
