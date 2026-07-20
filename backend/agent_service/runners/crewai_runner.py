"""CrewAI runner — code generation followed by parallel reviews.

Refactored from review_pipeline.py into the BaseRunner interface.
"""

import logging
import threading
import time
from crewai import Agent, Task, Crew, Process
from app.core.config import settings
from app.services import git_service as git
from agent_service.tools.file_tools import FileReadTool, FileWriteTool
from agent_service.tools.git_tools import GitDiffTool
from agent_service.tools.memory_tools import MemorySearchTool, MemoryRecordTool
from agent_service.tools.quality_gate_tools import QualityGateTool

from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

# Keep interactive task execution responsive. These values bound each model
# request and each individual CrewAI role without limiting a whole pipeline to
# one model turn.
LLM_REQUEST_TIMEOUT_SECONDS = 75
LLM_MAX_OUTPUT_TOKENS = 8192
AGENT_MAX_ITERATIONS = 12
# CrewAI runs an all-unlimited batch of native tools in a thread pool. The
# pipeline owns a workspace lock, so workspace tools must execute on that same
# thread. This cap is deliberately well above the iteration limit and only
# opts those tool calls out of CrewAI's parallel batch execution.
MAX_TOOL_CALLS_PER_AGENT = 50

# ── Stage definitions ─────────────────────────────────────────────────

STAGES = [
    {"key": "code_gen",   "label": "代码工程师", "icon": "code",    "desc": "正在生成代码..."},
    {"key": "reviewer",   "label": "代码审查员", "icon": "eye",     "desc": "正在检查代码质量..."},
    {"key": "security",   "label": "安全审查员", "icon": "shield",  "desc": "正在扫描安全漏洞..."},
    {"key": "summarizer", "label": "审查汇总员", "icon": "file",    "desc": "正在汇总审查报告..."},
]

STAGE_BY_TASK_PREFIX: dict[str, str] = {
    "任务描述": "code_gen",
    "请审查刚才代码工程师": "reviewer",
    "请审查刚才代码工程师生成的代码的安全性": "security",
    "请将代码审查员和安全审查员的审查意见汇总": "summarizer",
}


def _review_workspace_snapshot(workspace: str) -> str:
    """Capture one authoritative post-generation view for all reviewers."""
    try:
        nodes = git.list_files(workspace)
        paths: list[str] = []

        def collect(items: list[dict]) -> None:
            for item in items:
                if item.get("type") in ("dir", "tree"):
                    collect(item.get("children") or [])
                elif item.get("path"):
                    paths.append(item["path"])

        collect(nodes)
        paths = sorted(paths)[:200]
        diff = git.diff_vs_master(workspace)
        changed = "No changed files detected." if not diff else diff[:12000]
        files = "\n".join(f"- {path}" for path in paths) or "(no files)"
        return (
            "\n\n[AUTHORITATIVE WORKSPACE SNAPSHOT]\n"
            "This snapshot was captured by the orchestrator immediately after code generation. "
            "Both review roles receive the exact same snapshot. Do not claim the workspace is empty "
            "or omit a listed file without first reading it.\n"
            f"Files:\n{files}\n\nChanges versus base branch:\n{changed}\n"
            "[/AUTHORITATIVE WORKSPACE SNAPSHOT]\n"
        )
    except Exception as exc:
        logger.warning("Could not capture review workspace snapshot: %s", exc)
        return "\n\n[AUTHORITATIVE WORKSPACE SNAPSHOT]\nSnapshot unavailable; use FileRead and GitDiff before reporting.\n"


class CrewAIRunner(BaseRunner):
    """Execute code generation → parallel review/security → summary."""

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
        """Build and execute the CrewAI review DAG."""
        stage_state = {"key": "code_gen", "label": "代码工程师"}
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        started_at = time.monotonic()
        try:
            crew = self._build_crew(workspace, model_name, task_id, project_id, agent_id,
                                     on_progress, on_stage, stage_state)
            if on_progress:
                on_progress("⚙️  第 1/4 步：代码工程师正在生成代码...", "step_1_codegen")
                on_progress("🔍 Agent 正在查看现有代码结构，分析需求...", "step_1_detail")

            if on_progress:
                def _heartbeat() -> None:
                    while not heartbeat_stop.wait(12):
                        elapsed = int(time.monotonic() - started_at)
                        on_progress(
                            f"⏳ {stage_state['label']} 仍在执行中（已运行 {elapsed}s），正在等待模型或工具返回…",
                            f"{stage_state['key']}_heartbeat",
                        )

                heartbeat_thread = threading.Thread(
                    target=_heartbeat,
                    name=f"crewai-progress-{task_id}",
                    daemon=True,
                )
                heartbeat_thread.start()

            result = crew.kickoff(inputs={"task_description": task_description})

            # Report completion
            if on_progress:
                on_progress("✅ 第 2/4 步：代码审查完成", "step_2_done")
                on_progress("✅ 第 3/4 步：安全审查完成", "step_3_done")
                on_progress("✅ 第 4/4 步：审查报告汇总完成", "step_4_done")
            if on_stage:
                on_stage("reviewer", "done")
                on_stage("security", "done")
                on_stage("summarizer", "done")

            summary = str(result) if result else ""
            return RunResult(summary=summary)

        except Exception as e:
            logger.exception("CrewAI pipeline failed")
            return RunResult(error=str(e))
        finally:
            heartbeat_stop.set()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=1)

    def _build_crew(self, workspace: str, model_name: str,
                    task_id: int, project_id: int, agent_id: int,
                    on_progress: ProgressCallback | None,
                    on_stage: StageCallback | None,
                    stage_state: dict[str, str]) -> Crew:
        """Build code generation → parallel reviews → summary."""

        # Tools
        read_tool = FileReadTool(workspace=workspace, max_usage_count=MAX_TOOL_CALLS_PER_AGENT)
        write_tool = FileWriteTool(workspace=workspace, max_usage_count=MAX_TOOL_CALLS_PER_AGENT)
        diff_tool = GitDiffTool(workspace=workspace, max_usage_count=MAX_TOOL_CALLS_PER_AGENT)
        quality_gate_tool = QualityGateTool(
            workspace=workspace,
            max_usage_count=MAX_TOOL_CALLS_PER_AGENT,
        )
        mem_search = MemorySearchTool(
            task_id=task_id, agent_id=agent_id, project_id=project_id,
            max_usage_count=MAX_TOOL_CALLS_PER_AGENT,
        )
        mem_record = MemoryRecordTool(
            task_id=task_id, agent_id=agent_id, project_id=project_id,
            max_usage_count=MAX_TOOL_CALLS_PER_AGENT,
        )

        # LLM config
        # Use the application settings rather than os.getenv(): BaseSettings
        # reads .env itself and does not populate the process environment.
        api_key = settings.DEEPSEEK_API_KEY
        base_url = settings.DEEPSEEK_BASE_URL
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法启动 CrewAI Agent")

        llm_kwargs: dict = {
            "model": model_name,
            "api_key": api_key,
            "base_url": base_url,
            "timeout": LLM_REQUEST_TIMEOUT_SECONDS,
            "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        }
        # DeepSeek V4 enables thinking by default. Non-thinking mode keeps
        # ordinary coding tasks responsive while complex tasks can still use a
        # dedicated reasoning Agent/model when needed.
        if "api.deepseek.com" in base_url.lower() and model_name.startswith("deepseek-"):
            # CrewAI's OpenAI-compatible provider passes additional params to
            # `chat.completions.create()`. DeepSeek-only fields must therefore
            # be nested in `extra_body`, which the OpenAI client forwards as
            # raw JSON to the compatible API.
            llm_kwargs["additional_params"] = {
                "extra_body": {"thinking": {"type": "disabled"}},
            }

        # ── Agents ──────────────────────────────────────────────────

        code_gen = Agent(
            role="代码工程师",
            goal="精准实现任务要求的功能，把完整可运行的代码通过 FileWrite 工具真正写入项目文件",
            backstory=(
                "你是一位资深软件工程师，擅长Python、JavaScript、TypeScript等多个语言。"
                "你会认真分析需求，编写清晰、可维护的代码，并为每个函数添加适当注释。"
                "\n\n【核心工作准则】\n"
                "1. 严格聚焦：只实现任务明确要求的功能。不要擅自扩展需求、"
                "不要生成任务没有要求的脚手架、示例文件、配置文件或额外模块。"
                "如果任务只要求一个文件，就只写那一个文件。\n"
                "2. 代码必须落盘：你写的每一段代码都必须通过 FileWrite 工具实际写入文件。"
                "严禁只把代码贴在回答文本里而不调用 FileWrite——那样代码不会被保存，任务等于失败。\n"
                "3. 完整性：写入的代码必须是完整、可运行的，包含所有必要的导入、"
                "函数体和逻辑实现，不允许出现 TODO、pass 占位或省略号代替真实实现。\n"
                "4. 自检闭环：写完后必须用 GitDiff 工具确认目标文件确实已写入且内容非空，"
                "若发现核心文件缺失或为空，必须立即用 FileWrite 补写。\n\n"
                "编写代码前，先用 MemorySearch 查找项目中是否有相关的经验和模式。"
                "完成后，用 MemoryRecord 记录重要的设计决策供后续参考。"
            ),
            tools=[read_tool, write_tool, diff_tool, quality_gate_tool, mem_search, mem_record],
            verbose=True,
            allow_delegation=False,
            max_iter=AGENT_MAX_ITERATIONS,
            **({"llm": llm_kwargs} if llm_kwargs else {}),
        )

        reviewer = Agent(
            role="代码审查员",
            goal="审查代码质量：检查逻辑错误、命名规范、潜在bug和代码风格",
            backstory=(
                "你是一位严格的代码审查专家，有10年以上的代码审查经验。"
                "你会仔细检查每一行代码，关注：逻辑是否正确、命名是否清晰、"
                "是否有潜在的null/undefined错误、异常处理是否完善、代码是否可读。"
                "审查前先用 MemorySearch 查看项目历史中是否有类似问题被指出过。"
            ),
            tools=[read_tool, mem_search],
            verbose=True,
            allow_delegation=False,
            max_iter=AGENT_MAX_ITERATIONS,
            **({"llm": llm_kwargs} if llm_kwargs else {}),
        )

        security = Agent(
            role="安全审查员",
            goal="检查代码中的安全漏洞：注入攻击、越权访问、敏感信息泄露、不安全加密",
            backstory=(
                "你是一位资深安全工程师，精通OWASP十大安全风险。"
                "你会检查：SQL注入、XSS、命令注入、路径遍历、硬编码密钥、"
                "不安全的加密算法、缺少输入验证等问题。"
                "审查前先用 MemorySearch 查看项目中是否有已知的安全关注点。"
            ),
            tools=[read_tool, mem_search],
            verbose=True,
            allow_delegation=False,
            max_iter=AGENT_MAX_ITERATIONS,
            **({"llm": llm_kwargs} if llm_kwargs else {}),
        )

        summarizer = Agent(
            role="审查汇总员",
            goal="将多名审查员的意见汇总为一份清晰、有条理的审查报告",
            backstory=(
                "你是一位技术项目经理，擅长将技术审查意见整理成"
                "结构化的报告。你会保留关键问题，合并重复意见，"
                "并按严重程度排序。汇总完成后，用 MemoryRecord "
                "将有价值的发现记录到项目记忆中。"
            ),
            tools=[mem_search, mem_record],
            verbose=True,
            allow_delegation=False,
            max_iter=AGENT_MAX_ITERATIONS,
            **({"llm": llm_kwargs} if llm_kwargs else {}),
        )

        # ── Tasks ───────────────────────────────────────────────────

        code_task = Task(
            description=(
                "任务描述：{task_description}\n\n"
                "请严格按以下步骤完成，不要偏离任务范围：\n"
                "1. 用 MemorySearch 搜索类似任务的历史经验（尤其是过去被审查驳回的错误模式，避免重犯）\n"
                "2. 用 FileRead 工具查看现有代码结构，理解上下文\n"
                "3. 仔细分析任务要求，明确『到底需要哪些文件』——"
                "只实现任务要求的功能，不要生成任务没要求的脚手架、示例、配置或额外模块\n"
                "4. 【关键】用 FileWrite 工具把每一个文件的完整代码真正写入磁盘。"
                "代码只能通过 FileWrite 落盘，禁止只在回答里贴代码而不调用工具\n"
                "5. 用 GitDiff 工具确认你的改动——逐一核对任务要求的每个核心文件"
                "是否都已出现在 diff 中且内容非空。若有遗漏或为空，立即用 FileWrite 补写后再次 GitDiff 确认\n"
                "6. 用 DeterministicQualityGate 运行审批前七项检查。若提示“可由 Agent 修复”，"
                "必须继续修改代码或测试并再次运行；不得只解释失败原因。"
                "若提示“需平台管理员处理”，记录该项但不要伪造依赖或测试结果\n"
                "7. 用 MemoryRecord 记录重要的设计决策（scope: project）\n\n"
                "硬性要求：\n"
                "- 生成的代码必须完整可运行，包含所有必要导入、完整函数体，"
                "不允许 TODO / pass 占位 / 省略号代替真实实现\n"
                "- 不要生成任务范围之外的任何文件\n"
                "- 结束前必须通过 GitDiff 确认所有核心文件已真实落盘，并至少运行一次 "
                "DeterministicQualityGate"
            ),
            expected_output=(
                "一份说明，包含：(1) 实际通过 FileWrite 写入的文件路径列表；"
                "(2) 每个文件的作用简述；(3) GitDiff 自检结论，确认所有核心文件均已落盘且内容非空。"
            ),
            agent=code_gen,
        )

        review_task = Task(
            description=(
                "请审查刚才代码工程师生成的代码变更：\n"
                "1. 用 MemorySearch 搜索项目中历史审查发现过的问题模式\n"
                "2. 【落盘校验 — 最高优先级】对照原任务要求，用 GitDiff/FileRead 确认"
                "任务要求的每个核心文件是否都已真实写入且内容非空、逻辑完整。"
                "若发现任务要求的核心文件缺失、为空、或只有占位实现（TODO/pass/省略号），"
                "必须标记为『高』严重程度问题并明确指出缺失的文件名——这是必须驳回的问题\n"
                "3. 检查是否生成了任务范围之外的多余文件（脚手架/示例/无关模块），"
                "若有则标记为『中』严重程度问题\n"
                "4. 用 FileRead 工具读取所有被修改的文件\n"
                "5. 检查：逻辑正确性、命名规范、错误处理、代码风格\n"
                "6. 对每个问题给出：文件路径、行号（若能确定）、严重程度（高/中/低）、具体建议\n\n"
                "原任务：{task_description}"
            ),
            expected_output=(
                "结构化的审查意见列表，按严重程度排序。"
                "必须在开头明确给出『核心文件落盘校验结论』（是否所有要求的文件都已完整落盘）。"
            ),
            agent=reviewer,
            # These two reviews only depend on the generated files, not on
            # each other. CrewAI schedules adjacent async tasks concurrently.
            async_execution=True,
        )

        security_task = Task(
            description=(
                "请审查刚才代码工程师生成的代码的安全性：\n"
                "1. 用 MemorySearch 搜索项目中是否有已知的安全关注点\n"
                "2. 用 FileRead 工具读取所有被修改的文件\n"
                "3. 检查：SQL注入、XSS、命令注入、路径遍历、硬编码密钥/密码、"
                "不安全加密算法(HMAC/MD5)、输入验证缺失、认证授权问题\n"
                "4. 对每个问题给出：文件路径、漏洞类型、严重程度、修复建议\n\n"
                "原任务：{task_description}"
            ),
            expected_output="结构化的安全审查意见列表",
            agent=security,
            async_execution=True,
        )

        summary_task = Task(
            description=(
                "请将代码审查员和安全审查员的审查意见汇总为一份统一报告。"
                "所有输出必须使用中文。\n"
                "报告结构：\n"
                "## 审查总结\n（总体评价，1-2句话）\n"
                "## 严重问题\n（高危问题，必须修复）\n"
                "## 一般问题\n（中等问题，建议修复）\n"
                "## 建议改进\n（低优先级改进建议）\n"
                "## 审查结论\n（是否建议通过/需要修改）\n\n"
                "最后，用 MemoryRecord 将本次审查中值得注意的发现"
                "记录到项目记忆（scope: project）或全局记忆（scope: global）。"
            ),
            expected_output="结构化的 Markdown 中文审查报告",
            agent=summarizer,
            # A synchronous task after async tasks waits for both outputs and
            # receives them as explicit context.
            context=[review_task, security_task],
        )

        # ── Task callback factory ───────────────────────────────────

        stage_labels = {
            "code_gen": "代码工程师",
            "reviewer": "代码审查员",
            "security": "安全审查员",
            "summarizer": "审查汇总员",
        }
        completed_stages: set[str] = set()
        callback_lock = threading.Lock()

        def _step_callback(step) -> None:
            """Forward CrewAI's ReAct steps (especially tool calls) to the UI."""
            if not on_progress:
                return
            tool_name = str(getattr(step, "tool", "")).strip()
            stage_key = stage_state["key"]
            label = stage_state["label"]
            if tool_name:
                on_progress(f"🔧 {label} 正在调用工具：{tool_name}", f"{stage_key}_tool")
            else:
                on_progress(f"🧠 {label} 已完成一轮推理，正在继续处理…", f"{stage_key}_step")

        def _task_callback(task_output):
            desc = getattr(task_output, "description", "")
            stage_key = None
            for prefix, key in STAGE_BY_TASK_PREFIX.items():
                if prefix in desc:
                    stage_key = key
                    break
            if not stage_key:
                idx = len(completed_stages)
                keys = [s["key"] for s in STAGES]
                if idx < len(keys):
                    stage_key = keys[idx]
                else:
                    return
            # Async review callbacks are invoked from different worker
            # threads.  Deduplicate and advance the DAG under one lock.
            with callback_lock:
                if stage_key in completed_stages:
                    return
                completed_stages.add(stage_key)
            if stage_key == "code_gen":
                snapshot = _review_workspace_snapshot(workspace)
                # The two async review tasks start only after this callback.
                # Give them identical, orchestration-produced evidence rather
                # than letting each infer the workspace state independently.
                review_task.description += snapshot
                security_task.description += snapshot
            if on_stage:
                on_stage(stage_key, "done")
            if on_progress:
                stage_info = next((s for s in STAGES if s["key"] == stage_key), None)
                label = stage_info["label"] if stage_info else stage_key
                on_progress(f"✅ {label}完成", f"stage_{stage_key}_done")

            if stage_key == "code_gen":
                stage_state["key"] = "parallel_review"
                stage_state["label"] = "代码审查员与安全审查员"
                if on_stage:
                    on_stage("reviewer", "running")
                    on_stage("security", "running")
                if on_progress:
                    on_progress("▶️ 代码审查员与安全审查员开始并行执行", "parallel_review_start")
            elif stage_key in {"reviewer", "security"}:
                with callback_lock:
                    reviews_finished = {"reviewer", "security"}.issubset(completed_stages)
                if reviews_finished:
                    stage_state["key"] = "summarizer"
                    stage_state["label"] = stage_labels["summarizer"]
                    if on_stage:
                        on_stage("summarizer", "running")
                    if on_progress:
                        on_progress(f"▶️ {stage_state['label']} 开始执行", "stage_summarizer_start")

        # ── Crew ────────────────────────────────────────────────────

        return Crew(
            agents=[code_gen, reviewer, security, summarizer],
            tasks=[code_task, review_task, security_task, summary_task],
            process=Process.sequential,
            verbose=True,
            step_callback=_step_callback,
            task_callback=_task_callback,
        )
