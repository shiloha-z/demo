"""Claude Code runner — calls the locally installed `claude` CLI via subprocess.

Uses `claude -p` (non-interactive print mode) with `--permission-mode acceptEdits`
to run 4 sequential stages: code_gen → reviewer → security → summarizer.

Each stage runs as an independent `claude -p` call. File context is preserved on disk
between stages — stage 2 reads files that stage 1 wrote, etc.

Requires: Claude Code CLI installed (`claude` on PATH)
Requires: User already authenticated (`claude` login done)
"""

import os
import json
import asyncio
import logging
from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

# Check if claude CLI is available
import shutil
_HAS_CLI = shutil.which("claude") is not None

# Stage definitions
STAGES = [
    {"key": "code_gen",   "label": "代码工程师",
     "prompt": (
         "You are a senior software engineer. Based on the task below, analyze the "
         "existing codebase first (read relevant files), then write the required code. "
         "Write complete, production-quality code with comments. Use Edit/Write tools.\n\n"
         "Task: {task_description}"
     )},
    {"key": "reviewer",   "label": "代码审查员",
     "prompt": (
         "You are a strict code reviewer. Review ALL the code changes in this workspace. "
         "Read every modified file. Check for: logic errors, naming, potential bugs "
         "(null/undefined, edge cases), error handling, code readability. "
         "List each issue with: file path, severity (high/medium/low), and fix suggestion."
     )},
    {"key": "security",   "label": "安全审查员",
     "prompt": (
         "You are a security engineer. Audit ALL code in this workspace for vulnerabilities. "
         "Check: SQL injection, XSS, command injection, path traversal, hardcoded secrets/keys, "
         "insecure encryption (MD5, weak ciphers), missing input validation, auth issues. "
         "For each finding: file path, vulnerability type, severity, fix recommendation."
     )},
    {"key": "summarizer", "label": "审查汇总员",
     "prompt": (
         "You are a tech lead. Consolidate the code review and security audit findings "
         "into a single structured Markdown report:\n"
         "## 审查总结\n(1-2 sentence overall assessment)\n"
         "## 严重问题\n(must-fix high-severity issues)\n"
         "## 一般问题\n(medium-severity, suggested fixes)\n"
         "## 建议改进\n(low-priority improvements)\n"
         "## 审查结论\n(pass / changes needed)"
     )},
]


class ClaudeCodeRunner(BaseRunner):
    """Execute the review pipeline by calling the local `claude` CLI."""

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
        if not _HAS_CLI:
            return RunResult(error=(
                "Claude Code CLI not found on PATH.\n"
                "Install: https://claude.ai/code\n"
                "Then run `claude` once to authenticate."
            ))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self._async_run(task_description, workspace, model_name,
                           task_id, project_id, on_progress, on_stage)
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
        all_outputs: list[str] = []

        for i, stage in enumerate(STAGES):
            if on_stage:
                on_stage(stage["key"], "running")
            if on_progress:
                on_progress(
                    f"第 {i + 1}/4 步：{stage['label']}（Claude Code）",
                    f"step_{i + 1}_{stage['key']}",
                )

            prompt = stage["prompt"].format(task_description=task_description)

            try:
                output = await self._run_claude(workspace, model_name, prompt, on_progress)
                all_outputs.append(output)
            except Exception as e:
                logger.error(f"Claude Code stage '{stage['key']}' failed: {e}")
                if on_progress:
                    on_progress(f"❌ {stage['label']}失败: {e}", f"stage_{stage['key']}_error")
                if on_stage:
                    on_stage(stage["key"], "error")
                return RunResult(error=f"Stage '{stage['key']}' failed: {e}")

            if on_stage:
                on_stage(stage["key"], "done")
            if on_progress:
                on_progress(f"✅ {stage['label']}完成", f"stage_{stage['key']}_done")

        return RunResult(summary=all_outputs[-1] if all_outputs else "")

    async def _run_claude(
        self,
        workspace: str,
        model: str,
        prompt: str,
        on_progress: ProgressCallback | None,
    ) -> str:
        """Run a single `claude -p` command and collect output."""

        cmd = [
            "claude", "-p", prompt,
            "--permission-mode", "acceptEdits",
            "--max-turns", "30",
        ]
        if model:
            cmd.extend(["--model", model])

        env = os.environ.copy()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env=env,
        )

        stdout_text = ""
        stderr_text = ""

        # Read stdout + stderr concurrently
        async def read_stream(stream, is_stderr: bool):
            nonlocal stdout_text, stderr_text
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if is_stderr:
                    stderr_text += text + "\n"
                else:
                    stdout_text += text + "\n"
                    # Forward as progress
                    if on_progress and text:
                        on_progress(f"  {text[:200]}", "claude_output")

        if proc.stdout and proc.stderr:
            await asyncio.gather(
                read_stream(proc.stdout, False),
                read_stream(proc.stderr, True),
            )

        await proc.wait()

        if proc.returncode != 0 and not stdout_text.strip():
            error_msg = stderr_text.strip() or f"exit code {proc.returncode}"
            raise RuntimeError(f"Claude Code failed: {error_msg}")

        return stdout_text.strip()
