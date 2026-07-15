"""OpenCode runner — OpenCode CLI as a subprocess.

Uses `opencode run --format json` in non-interactive mode to execute
the 4-stage review pipeline.

Requires: OpenCode CLI installed (https://opencode.ai)
"""

import os
import json
import shutil
import asyncio
import logging
from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

# Stage instructions (same as Claude runner, adapted for OpenCode)
STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",
     "prompt": "Based on the task description below, analyze the existing codebase, "
               "then write the required code. Use read/write tools. Write complete, "
               "production-quality code with comments.\n\nTask: {task_description}"},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",
     "prompt": "Review ALL the code you just generated. Check for: logic errors, "
               "naming, potential bugs, error handling, code readability. "
               "List each issue with: file path, severity (high/medium/low), and fix suggestion."},
    {"key": "security",   "label": "安全审查员", "icon": "shield",
     "prompt": "Security audit of the code. Check: SQL injection, XSS, command injection, "
               "path traversal, hardcoded secrets, insecure encryption, missing input validation. "
               "For each finding: file path, vulnerability type, severity, fix recommendation."},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",
     "prompt": "Consolidate the review and security findings into a structured Markdown report:\n"
               "## 审查总结\n## 严重问题\n## 一般问题\n## 建议改进\n## 审查结论"},
]

_OPENCODE_PATH = shutil.which("opencode")


class OpenCodeRunner(BaseRunner):
    """Execute the review pipeline via OpenCode CLI.

    Requires `opencode` CLI to be installed and available on PATH.
    Uses `opencode run --format json` for machine-readable output.
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
        if not _OPENCODE_PATH:
            return RunResult(error=(
                "OpenCode CLI is not installed or not on PATH.\n"
                "Install it: curl -fsSL https://opencode.ai/install | bash\n"
                "Or: pip install opencode-cli"
            ))

        try:
            # Run async operations via asyncio
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
        except Exception as e:
            logger.exception("OpenCode runner failed")
            return RunResult(error=str(e))

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
        all_outputs: list[str] = []

        for i, stage in enumerate(STAGES):
            if on_stage:
                on_stage(stage["key"], "running")
            if on_progress:
                on_progress(
                    f"第 {i + 1}/4 步：{stage['label']}（OpenCode）",
                    f"step_{i + 1}_{stage['key']}",
                )

            prompt = stage["prompt"].format(task_description=task_description)

            try:
                output = await self._run_opencode(workspace, model_name, prompt, on_progress)
                all_outputs.append(output)
            except Exception as e:
                logger.error(f"OpenCode stage {stage['key']} failed: {e}")
                if on_progress:
                    on_progress(f"❌ {stage['label']}失败: {e}", f"stage_{stage['key']}_error")
                if on_stage:
                    on_stage(stage["key"], "error")
                return RunResult(error=f"Stage '{stage['key']}' failed: {e}")

            if on_stage:
                on_stage(stage["key"], "done")
            if on_progress:
                on_progress(f"✅ {stage['label']}完成", f"stage_{stage['key']}_done")

        final_summary = all_outputs[-1] if all_outputs else ""
        return RunResult(summary=final_summary)

    async def _run_opencode(
        self,
        workspace: str,
        model: str,
        prompt: str,
        on_progress: ProgressCallback | None,
    ) -> str:
        """Run a single OpenCode command and collect output."""
        env = os.environ.copy()
        if "ANTHROPIC_API_KEY" in env:
            model_flag = model or "anthropic/claude-sonnet-4-20250514"
        else:
            model_flag = model or "deepseek/deepseek-chat"

        cmd = [
            _OPENCODE_PATH, "run",
            "--format", "json",
            "--model", model_flag,
            "--cwd", workspace,
            "--no-interactive",
            prompt,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout_lines: list[str] = []
        if proc.stdout:
            async for line in proc.stdout:
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    stdout_lines.append(text)
                    # Try to parse JSON event for progress
                    try:
                        event = json.loads(text)
                        if isinstance(event, dict):
                            msg = event.get("message") or event.get("text") or ""
                            if msg and on_progress:
                                on_progress(f"  {str(msg)[:200]}", "opencode_output")
                    except json.JSONDecodeError:
                        if on_progress:
                            on_progress(f"  {text[:200]}", "opencode_output")
                except Exception:
                    pass

        stderr_text = ""
        if proc.stderr:
            stderr_data = await proc.stderr.read()
            stderr_text = stderr_data.decode("utf-8", errors="replace")

        await proc.wait()

        if proc.returncode != 0 and not stdout_lines:
            return f"[OpenCode exited with code {proc.returncode}]\n{stderr_text}"

        return "\n".join(stdout_lines) if stdout_lines else stderr_text
