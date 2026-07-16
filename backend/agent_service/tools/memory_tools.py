"""CrewAI tools for the ChromaDB task / agent / project / global hierarchy.

Each agent in the pipeline can:
  - Search memories (task → agent → project → global) before acting
  - Record observations and decisions after acting

Tools are workspace-scoped so they know which task/project they belong to.
"""

from crewai.tools import BaseTool


class MemorySearchTool(BaseTool):
    """Search all memory layers for relevant context.

    Use this BEFORE making changes to understand:
      - What this Agent learned on prior assignments (agent memory)
      - What patterns worked or failed before (project/global memory)
      - What was discussed earlier in this task (task memory)
    """

    name: str = "MemorySearch"
    description: str = (
        "Search the task → agent → project → global memory hierarchy. "
        "Returns task memory (this run), Agent memory (this configured Agent), "
        "project memory (across tasks in this project), and global memory. "
        "Input: a search query string describing what you want to know."
    )

    task_id: int = 0
    agent_id: int = 0
    project_id: int = 0

    def _run(self, query: str) -> str:
        from app.services.memory_service import search_all

        results = search_all(
            self.task_id,
            self.project_id,
            query,
            n_results=3,
            agent_id=self.agent_id,
        )

        lines: list[str] = []
        for layer, docs in results.items():
            label = {
                "task": "📋 任务记忆",
                "agent": "🤖 Agent 记忆",
                "project": "📁 项目记忆",
                "global": "🌐 全局记忆",
            }.get(layer, layer)
            if docs:
                lines.append(f"\n### {label}")
                for i, doc in enumerate(docs, 1):
                    lines.append(f"{i}. {doc}")
            else:
                lines.append(f"\n### {label}\n(无结果)")

        return "\n".join(lines).strip() if lines else "未找到相关记忆。"


class MemoryRecordTool(BaseTool):
    """Record a new observation or decision into the appropriate memory layer.

    Use this AFTER completing a step to share what you learned:
      - task-level: context useful only during this execution
      - agent-level: this configured Agent's reusable working habits
      - project-level: patterns specific to this project
      - global-level: general lessons for any project
    """

    name: str = "MemoryRecord"
    description: str = (
        "Record an insight or lesson learned. "
        "Input format: 'SCOPE: content' where SCOPE is task, agent, project, or global. "
        "Use agent for reusable lessons specific to this Agent, and project for shared codebase facts. "
        "Example: 'project: SQLite connection pooling should use check_same_thread=False' "
        "Example: 'global: Always sanitize file paths before writing to disk'"
    )

    task_id: int = 0
    agent_id: int = 0
    project_id: int = 0

    def _run(self, input_str: str) -> str:
        from app.services.memory_service import (
            add_agent_memory,
            add_global_memory,
            add_project_memory,
            add_task_memory,
        )

        scope, content = "project", input_str
        if ":" in input_str:
            parts = input_str.split(":", 1)
            if parts[0].strip().lower() in ("task", "agent", "project", "global"):
                scope = parts[0].strip().lower()
                content = parts[1].strip()

        metadata = {
            "task_id": str(self.task_id),
            "project_id": str(self.project_id),
            "agent_id": str(self.agent_id),
            "source": "crewai_tool",
        }
        if scope == "task":
            uid = add_task_memory(self.task_id, content, metadata)
            return f"✅ 已记录到任务记忆 [{uid}]"
        if scope == "agent":
            uid = add_agent_memory(self.agent_id, content, metadata)
            return f"✅ 已记录到 Agent 记忆 [{uid}]" if uid else "Agent 记忆不可用"
        if scope == "global":
            uid = add_global_memory(content, metadata)
            return f"✅ 已记录到全局记忆 [{uid}]"
        else:
            uid = add_project_memory(self.project_id, content, metadata)
            return f"✅ 已记录到项目记忆 [{uid}]"
