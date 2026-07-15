"""Claude Code runner — Anthropic Claude Agent SDK.

Uses a single ClaudeSDKClient session with 4 sequential prompts
to replicate the pipeline stages: code_gen → reviewer → security → summarizer.

Requires: pip install claude-agent-sdk
Requires: ANTHROPIC_API_KEY env var (or set via ClaudeAgentOptions)
"""

import os
import logging
import shutil
from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

# Stage definitions (same order as CrewAI pipeline)
STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",
     "instruction": "Step 1 — Code Generation: Based on the task description below, "
                    "analyze the existing codebase, then write the required code. "
                    "Use file read/write tools. Read existing files first to understand the structure. "
                    "Write complete, production-quality code with comments.\n\n"
                    "Task: {task_description}"},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",
     "instruction": "Step 2 — Code Review: Review ALL the code you just generated. "
                    "Check for: logic errors, naming conventions, potential bugs (null/undefined, "
                    "race conditions), error handling, code readability. "
                    "List each issue with: file path, severity (high/medium/low), and specific fix suggestion."},
    {"key": "security",   "label": "安全审查员", "icon": "shield",
     "instruction": "Step 3 — Security Audit: Review the code for security vulnerabilities. "
                    "Check: SQL injection, XSS, command injection, path traversal, hardcoded secrets/keys, "
                    "insecure encryption (MD5, weak ciphers), missing input validation, auth issues. "
                    "For each finding provide: file path, vulnerability type, severity, fix recommendation."},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",
     "instruction": "Step 4 — Summary Report: Consolidate the code review and security audit findings "
                    "into a single structured report in Markdown:\n"
                    "## 审查总结\n(1-2 sentence overall assessment)\n"
                    "## 严重问题\n(must-fix high-severity issues)\n"
                    "## 一般问题\n(medium-severity, suggested fixes)\n"
                    "## 建议改进\n(low-priority improvements)\n"
                    "## 审查结论\n(pass / changes needed)"},
]

# Check if Claude Agent SDK is available
_HAS_SDK = shutil.which("claude") is not None or os.getenv("ANTHROPIC_API_KEY", "")


class ClaudeCodeRunner(BaseRunner):
    """Execute the review pipeline using Claude Agent SDK.

    Uses one persistent session with 4 sequential prompts, one per pipeline stage.
    This gives clean stage separation while keeping full context across stages.
    """

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
        if not _HAS_SDK:
            return RunResult(error=(
                "Claude Agent SDK is not available. "
                "Install it with: pip install claude-agent-sdk\n"
                "And set ANTHROPIC_API_KEY in your .env file."
            ))

        try:
            return self._run_with_sdk(
                task_description, workspace, model_name,
                task_id, project_id, on_progress, on_stage,
            )
        except ImportError as e:
            return RunResult(error=(
                f"Claude Agent SDK import failed: {e}\n"
                "Install it with: pip install claude-agent-sdk"
            ))
        except Exception as e:
            logger.exception("Claude Code runner failed")
            return RunResult(error=str(e))

    def _run_with_sdk(
        self,
        task_description: str,
        workspace: str,
        model_name: str,
        task_id: int,
        project_id: int,
        on_progress: ProgressCallback | None,
        on_stage: StageCallback | None,
    ) -> RunResult:
        """Execute using the Claude Agent SDK."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self._async_run(
                task_description, workspace, model_name,
                task_id, project_id, on_progress, on_stage,
            )
        )

    async def _async_run(
        self,
        task_description: str,
        workspace: str,
        model_name: str,
        task_id: int,
        project_id: int,
        on_progress: ProgressCallback | None,
        on_stage: StageCallback | None,
    ) -> RunResult:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, tool, create_sdk_mcp_server

        # ── Register custom tools ───────────────────────────────────

        @tool("FileRead", "Read a file from the project workspace", {"path": str})
        async def file_read(args):
            from .tool_adapters import read_file
            result = read_file(workspace, args["path"])
            return {"content": [{"type": "text", "text": result}]}

        @tool("FileWrite", "Write content to a file in the project workspace",
              {"path": str, "content": str})
        async def file_write(args):
            from .tool_adapters import write_file
            result = write_file(workspace, args["path"], args["content"])
            return {"content": [{"type": "text", "text": result}]}

        @tool("GitDiff", "Show current git diff of all changes", {})
        async def git_diff(_args):
            from .tool_adapters import get_diff
            result = get_diff(workspace)
            return {"content": [{"type": "text", "text": result}]}

        @tool("MemorySearch", "Search project/global memory for relevant knowledge",
              {"query": str})
        async def memory_search(args):
            from .tool_adapters import search_memory
            result = search_memory(task_id, project_id, args["query"])
            return {"content": [{"type": "text", "text": result}]}

        @tool("MemoryRecord", "Record an insight to project or global memory",
              {"scope": str, "content": str})
        async def memory_record(args):
            from .tool_adapters import record_memory
            result = record_memory(task_id, project_id, args["scope"], args["content"])
            return {"content": [{"type": "text", "text": result}]}

        server = create_sdk_mcp_server(
            "workspace_tools", version="1.0.0",
            tools=[file_read, file_write, git_diff, memory_search, memory_record],
        )

        # ── System prompt ───────────────────────────────────────────

        system_prompt = (
            "You are a multi-stage code review agent. You will work through 4 stages "
            "sequentially in a single session. At each stage, focus ONLY on that stage's task.\n\n"
            "Available tools:\n"
            "- FileRead: Read files from the workspace\n"
            "- FileWrite: Write code files\n"
            "- GitDiff: See current changes\n"
            "- MemorySearch: Search knowledge base\n"
            "- MemoryRecord: Save findings\n\n"
            "Work primarily in the workspace directory. Write complete, production-quality code."
        )

        # ── Build options ───────────────────────────────────────────

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            permission_mode="acceptEdits",
            cwd=workspace,
            max_turns=100,
            model=model_name or "claude-sonnet-4-20250514",
            mcp_servers={"ws": server},
            allowed_tools=[
                "Read", "Write", "Edit", "Glob", "Grep", "Bash",
                "mcp__ws__FileRead", "mcp__ws__FileWrite", "mcp__ws__GitDiff",
                "mcp__ws__MemorySearch", "mcp__ws__MemoryRecord",
            ],
        )

        # ── Execute 4-stage pipeline ────────────────────────────────

        async with ClaudeSDKClient(options=options) as client:
            all_outputs: list[str] = []

            for i, stage in enumerate(STAGES):
                # Announce stage
                if on_stage:
                    on_stage(stage["key"], "running")
                if on_progress:
                    on_progress(
                        f"第 {i + 1}/4 步：{stage['label']}{stage['desc']}",
                        f"step_{i + 1}_{stage['key']}",
                    )

                instruction = stage["instruction"].format(task_description=task_description)

                await client.query(instruction)
                stage_output = ""
                async for msg in client.receive_response():
                    # Extract text content for progress
                    from claude_agent_sdk import AssistantMessage, TextBlock
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock) and block.text:
                                text = block.text[:200]
                                if on_progress:
                                    on_progress(f"  {text}", f"stage_{stage['key']}_output")
                                stage_output += block.text + "\n"

                all_outputs.append(stage_output)

                # Mark stage done
                if on_stage:
                    on_stage(stage["key"], "done")
                if on_progress:
                    on_progress(f"✅ {stage['label']}完成", f"stage_{stage['key']}_done")

        # Return the final stage's output as the summary
        final_summary = all_outputs[-1] if all_outputs else ""
        return RunResult(summary=final_summary)
