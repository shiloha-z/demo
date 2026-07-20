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
from pathlib import Path
from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

import shutil


def _find_claude_cli() -> str | None:
    """Return the native executable, not the Windows ``claude.CMD`` shim.

    A .CMD shim forwards ``%*`` through cmd.exe.  Long prompts containing
    non-ASCII text or shell metacharacters can therefore be altered before
    Claude Code receives them.  The npm package includes claude.exe next to
    that shim, so prefer it whenever it is available.
    """
    command = shutil.which("claude")
    if not command:
        return None
    command_path = Path(command)
    if os.name == "nt" and command_path.suffix.lower() in {".cmd", ".bat"}:
        native = command_path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if native.is_file():
            return str(native)
    return command


_CLAUDE_PATH = _find_claude_cli()

# Stage definitions
STAGES = [
    {"key": "code_gen",   "label": "代码工程师",
     "prompt": (
         "You are a senior software engineer. The complete user task is included "
         "verbatim inside <user_task> below. Do not ask the user to provide the task "
         "again; implement it directly. First analyze the "
         "existing codebase first (read relevant files), then write the required code. "
         "Write complete, production-quality code with comments (Chinese or English). "
         "Use Edit/Write tools. Your response to the user must be in Chinese.\n\n"
         "<user_task>\n{task_description}\n</user_task>"
     )},
    {"key": "reviewer",   "label": "代码审查员",
     "prompt": (
         "你是一位严格的代码审查专家。请审查此工作区中的所有代码变更。"
         "仔细阅读每个被修改的文件。检查：逻辑错误、命名规范、潜在 bug "
         "（空值/边界情况）、错误处理、代码可读性。"
         "对每个问题列出：文件路径、严重程度（高/中/低）、修复建议。"
         "所有输出必须使用中文。"
     )},
    {"key": "security",   "label": "安全审查员",
     "prompt": (
         "你是一位资深安全工程师。请审计此工作区中所有代码的安全漏洞。"
         "检查：SQL 注入、XSS、命令注入、路径遍历、硬编码密钥/密码、"
         "不安全加密（MD5、弱密码套件）、输入验证缺失、认证授权问题。"
         "对每个发现给出：文件路径、漏洞类型、严重程度、修复建议。"
         "所有输出必须使用中文。"
     )},
    {"key": "summarizer", "label": "审查汇总员",
     "prompt": (
         "你是一位技术主管。请将代码审查和安全审查的发现整合为一份结构化的 Markdown 报告：\n"
         "## 审查总结\n（1-2 句话的总体评价）\n"
         "## 严重问题\n（必须修复的高危问题）\n"
         "## 一般问题\n（中等严重程度，建议修复）\n"
         "## 建议改进\n（低优先级的改进建议）\n"
         "## 审查结论\n（通过 / 需要修改）\n\n"
         "所有输出必须使用中文。"
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
        agent_id: int = 0,
        *,
        enable_planning: bool = False,
        max_subtasks: int = 6,
        on_progress: ProgressCallback | None = None,
        on_stage: StageCallback | None = None,
    ) -> RunResult:
        if not _CLAUDE_PATH:
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
            _CLAUDE_PATH, "-p", prompt,
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
