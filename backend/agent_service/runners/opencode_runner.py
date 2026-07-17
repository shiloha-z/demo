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

# Stage instructions (adapted for OpenCode, Chinese output enforced)
STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",
     "prompt": "You are a senior software engineer. Based on the task below, analyze the "
               "existing codebase, then write the required code. Use read/write tools. "
               "Write complete, production-quality code with comments. "
               "Respond to the user in Chinese.\n\nTask: {task_description}"},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",
     "prompt": "你是一位严格的代码审查专家。审查所有代码变更。检查：逻辑错误、命名规范、"
               "潜在 bug、错误处理、代码可读性。对每个问题列出：文件路径、严重程度（高/中/低）、"
               "修复建议。所有输出必须使用中文。"},
    {"key": "security",   "label": "安全审查员", "icon": "shield",
     "prompt": "你是一位资深安全工程师。审计代码安全漏洞。检查：SQL 注入、XSS、命令注入、"
               "路径遍历、硬编码密钥、不安全加密、输入验证缺失。对每个发现给出：文件路径、"
               "漏洞类型、严重程度、修复建议。所有输出必须使用中文。"},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",
     "prompt": "你是一位技术主管。将审查和安全发现整合为结构化的 Markdown 报告：\n"
               "## 审查总结\n## 严重问题\n## 一般问题\n## 建议改进\n## 审查结论\n"
               "所有输出必须使用中文。"},
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
        agent_id: int = 0,
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
            "--dir", workspace,
            prompt,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout_lines: list[str] = []
        error_msg = ""
        if proc.stdout:
            async for line in proc.stdout:
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    stdout_lines.append(text)
                    # Try to parse JSON event
                    try:
                        event = json.loads(text)
                        if isinstance(event, dict):
                            # Check for error events first
                            if event.get("type") == "error":
                                err = event.get("error", {})
                                err_data = err.get("data", {}) if isinstance(err, dict) else {}
                                error_msg = err_data.get("message", "") or err.get("message", "") or str(err)
                                if on_progress:
                                    on_progress(f"❌ OpenCode 错误: {error_msg[:200]}", "opencode_error")
                                continue
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

        if error_msg:
            return f"[OpenCode 执行失败]\n{error_msg}"
        if proc.returncode != 0:
            return f"[OpenCode exited with code {proc.returncode}]\n{stderr_text}"

        return "\n".join(stdout_lines) if stdout_lines else stderr_text
