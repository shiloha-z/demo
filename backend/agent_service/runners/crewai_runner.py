"""CrewAI runner — 4-agent sequential review pipeline.

Refactored from review_pipeline.py into the BaseRunner interface.
"""

import os
import logging
from crewai import Agent, Task, Crew, Process
from agent_service.tools.file_tools import FileReadTool, FileWriteTool
from agent_service.tools.git_tools import GitDiffTool
from agent_service.tools.memory_tools import MemorySearchTool, MemoryRecordTool

from .base import BaseRunner, RunResult, ProgressCallback, StageCallback

logger = logging.getLogger(__name__)

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


class CrewAIRunner(BaseRunner):
    """Execute the 4-agent CrewAI review pipeline."""

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
        """Build and execute the CrewAI pipeline."""
        try:
            crew = self._build_crew(workspace, model_name, task_id, project_id,
                                    on_progress, on_stage)
            if on_progress:
                on_progress("⚙️  第 1/4 步：代码工程师正在生成代码...", "step_1_codegen")
                on_progress("🔍 Agent 正在查看现有代码结构，分析需求...", "step_1_detail")

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

    def _build_crew(self, workspace: str, model_name: str,
                    task_id: int, project_id: int,
                    on_progress: ProgressCallback | None,
                    on_stage: StageCallback | None) -> Crew:
        """Build the 4-agent CrewAI pipeline."""

        # Tools
        read_tool = FileReadTool(workspace=workspace)
        write_tool = FileWriteTool(workspace=workspace)
        diff_tool = GitDiffTool(workspace=workspace)
        mem_search = MemorySearchTool(task_id=task_id, project_id=project_id)
        mem_record = MemoryRecordTool(task_id=task_id, project_id=project_id)

        # LLM config
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        llm_kwargs: dict = {}
        if api_key:
            llm_kwargs = {
                "model": model_name,
                "api_key": api_key,
                "base_url": base_url,
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
            tools=[read_tool, write_tool, diff_tool, mem_search, mem_record],
            verbose=True,
            allow_delegation=False,
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
                "6. 用 MemoryRecord 记录重要的设计决策（scope: project）\n\n"
                "硬性要求：\n"
                "- 生成的代码必须完整可运行，包含所有必要导入、完整函数体，"
                "不允许 TODO / pass 占位 / 省略号代替真实实现\n"
                "- 不要生成任务范围之外的任何文件\n"
                "- 结束前必须通过 GitDiff 确认所有核心文件已真实落盘"
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
        )

        # ── Task callback factory ───────────────────────────────────

        completed_stages: list[str] = []

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
            completed_stages.append(stage_key)
            if on_stage:
                on_stage(stage_key, "done")
            if on_progress:
                stage_info = next((s for s in STAGES if s["key"] == stage_key), None)
                label = stage_info["label"] if stage_info else stage_key
                on_progress(f"✅ {label}完成", f"stage_{stage_key}_done")

        # ── Crew ────────────────────────────────────────────────────

        return Crew(
            agents=[code_gen, reviewer, security, summarizer],
            tasks=[code_task, review_task, security_task, summary_task],
            process=Process.sequential,
            verbose=True,
            task_callback=_task_callback,
        )
