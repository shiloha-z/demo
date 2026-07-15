"""Multi-agent code review pipeline using CrewAI.

Agents:
  1. CodeGen   — Generates code based on task description
  2. Reviewer  — Reviews code for logic, style, and bugs
  3. Security  — Checks for security vulnerabilities
  4. Summarizer — Consolidates all reviews into a single report

Each agent has access to:
  - FileRead/FileWrite/GitDiff tools (workspace-scoped)
  - MemorySearch/MemoryRecord tools (3-layer ChromaDB memory)
"""

import os
import logging
from crewai import Agent, Task, Crew, Process
from agent_service.tools.file_tools import FileReadTool, FileWriteTool
from agent_service.tools.git_tools import GitDiffTool
from agent_service.tools.memory_tools import MemorySearchTool, MemoryRecordTool

logger = logging.getLogger(__name__)


def build_crew(workspace_path: str, model_name: str = "deepseek-chat",
               task_id: int = 0, project_id: int = 0) -> Crew:
    """Build the review pipeline crew for a given workspace.

    Args:
        workspace_path: Path to the project workspace.
        model_name: LLM model to use (default: deepseek-chat).
        task_id: Current task ID (for memory scoping).
        project_id: Current project ID (for memory scoping).
    """

    # Tools scoped to this workspace
    read_tool = FileReadTool(workspace=workspace_path)
    write_tool = FileWriteTool(workspace=workspace_path)
    diff_tool = GitDiffTool(workspace=workspace_path)

    # Memory tools — scoped to this task+project
    mem_search = MemorySearchTool(task_id=task_id, project_id=project_id)
    mem_record = MemoryRecordTool(task_id=task_id, project_id=project_id)

    # LLM config — reads API key + base URL from env
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_kwargs: dict = {}
    if api_key:
        llm_kwargs = {
            "model": model_name,
            "api_key": api_key,
            "base_url": base_url,
        }

    # ── Agents ──────────────────────────────────────────────────────

    code_gen = Agent(
        role="代码工程师",
        goal="根据任务描述生成高质量、可运行的代码，并写入项目文件",
        backstory=(
            "你是一位资深软件工程师，擅长Python、JavaScript、TypeScript等多个语言。"
            "你会认真分析需求，编写清晰、可维护的代码，并为每个函数添加适当注释。"
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

    # ── Tasks ───────────────────────────────────────────────────────

    code_task = Task(
        description=(
            "任务描述：{task_description}\n\n"
            "请完成以下步骤：\n"
            "1. 用 MemorySearch 搜索类似任务的历史经验\n"
            "2. 先用 FileRead 工具查看现有代码结构\n"
            "3. 根据任务描述编写代码\n"
            "4. 用 FileWrite 工具将代码写入合适的文件\n"
            "5. 用 GitDiff 工具确认你的改动\n"
            "6. 用 MemoryRecord 记录重要的设计决策（scope: project）\n\n"
            "注意：请生成完整可运行的代码，包含必要的导入和注释。"
        ),
        expected_output="已写入的文件路径列表和代码说明",
        agent=code_gen,
    )

    review_task = Task(
        description=(
            "请审查刚才代码工程师生成的代码变更：\n"
            "1. 用 MemorySearch 搜索项目中历史审查发现过的问题模式\n"
            "2. 用 FileRead 工具读取所有被修改的文件\n"
            "3. 检查：逻辑正确性、命名规范、错误处理、代码风格\n"
            "4. 对每个问题给出：文件路径、行号（若能确定）、严重程度（高/中/低）、具体建议\n\n"
            "原任务：{task_description}"
        ),
        expected_output="结构化的审查意见列表，按严重程度排序",
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
            "请将代码审查员和安全审查员的审查意见汇总为一份统一报告。\n"
            "报告结构：\n"
            "## 审查总结\n（总体评价，1-2句话）\n"
            "## 严重问题\n（高危问题，必须修复）\n"
            "## 一般问题\n（中等问题，建议修复）\n"
            "## 建议改进\n（低优先级改进建议）\n"
            "## 审查结论\n（是否建议通过/需要修改）\n\n"
            "最后，用 MemoryRecord 将本次审查中值得注意的发现"
            "记录到项目记忆（scope: project）或全局记忆（scope: global）。"
        ),
        expected_output="结构化的Markdown审查报告",
        agent=summarizer,
    )

    # ── Crew ────────────────────────────────────────────────────────

    return Crew(
        agents=[code_gen, reviewer, security, summarizer],
        tasks=[code_task, review_task, security_task, summary_task],
        process=Process.sequential,
        verbose=True,
    )
