"""Lightweight task-planning step.

Before a planning-enabled agent executes a task, this module asks a model to
split the goal into a small, ordered set of self-contained subtasks. The runner
then drives those subtasks instead of the hard-coded single code-generation
task, which lets a single agent "decompose" its own work.

Design notes:
* Uses the OpenAI-compatible chat-completions endpoint directly via stdlib
  ``urllib`` so no new dependency is introduced and the caller's DeepSeek
  credentials/region are reused.
* Every failure (network, timeout, malformed JSON, cycle, empty plan) returns
  ``None`` so the caller can transparently fall back to the normal pipeline.
* The cost is bounded: one extra model turn with ``max_subtasks`` truncating the
  number of emitted steps.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Planning uses a thinking-disabled, non-reasoning call to stay fast and cheap.
# Bounded higher than the frontend's per-request timeout so the backend gets to
# decide (success, or a clear 422 fallback) instead of the client disconnecting
# first with a bare "timeout of 30000ms exceeded".
PLANNER_REQUEST_TIMEOUT_SECONDS = 150

# Generous token budget — truncated JSON is the most common silent failure mode.
PLANNER_MAX_TOKENS = 4096

# Number of retry attempts on transient failures (network, malformed JSON, etc.).
PLANNER_MAX_RETRIES = 2

# Directories that are never worth showing the planner (deps, caches, VCS).
_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".codebuddy", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", "target", "bin", "obj", "out", ".next", ".nuxt",
    "coverage", ".turbo", "site-packages", ".gradle",
}
# Files we skip in the structure tree (lockfiles / OS noise).
_IGNORE_FILES = {".DS_Store", "thumbs.db", "package-lock.json", "yarn.lock"}
# Only surface source-like files so the tree stays a meaningful, bounded signal.
_CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cpp",
    ".c", ".h", ".cs", ".rb", ".php", ".vue", ".svelte", ".kt", ".swift",
    ".scala", ".sh", ".sql", ".html", ".css", ".scss", ".less", ".md",
    ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini", ".xml",
    ".gradle", ".r", ".lua", ".dart",
}
# Marker files whose presence names the project's tech stack.
_STACK_MARKERS = (
    "package.json", "requirements.txt", "pyproject.toml", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "composer.json",
)


def collect_project_context(workspace: str, *, max_entries: int = 130, max_depth: int = 4) -> str:
    """Build a compact, bounded view of ``workspace`` for the planner.

    Returns a tree of source-relevant files plus a one-line tech-stack hint.
    An empty string is returned when the path is missing, so callers can pass
    it straight into :func:`plan_task` without branching.  The output is capped
    on both depth and entry count to keep the planner's input prompt bounded.
    """
    root = Path(workspace)
    if not root.exists() or not root.is_dir():
        return ""

    tree_lines: list[str] = []
    count = 0

    def walk(d: Path, depth: int, prefix: str) -> None:
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return
        try:
            items = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except (PermissionError, OSError):
            return
        dirs = [p for p in items if p.is_dir() and p.name not in _IGNORE_DIRS]
        files = [
            p for p in items
            if p.is_file() and p.suffix.lower() in _CODE_EXT and p.name not in _IGNORE_FILES
        ]
        rendered = [(p, True) for p in dirs] + [(p, False) for p in files]
        for i, (p, is_dir) in enumerate(rendered):
            if count >= max_entries:
                tree_lines.append(f"{prefix}… (更多文件已省略)")
                return
            last = i == len(rendered) - 1
            connector = "└── " if last else "├── "
            tree_lines.append(f"{prefix}{connector}{p.name}/" if is_dir else f"{prefix}{connector}{p.name}")
            count += 1
            if is_dir:
                walk(p, depth + 1, prefix + ("    " if last else "│   "))

    walk(root, 0, "")
    if not tree_lines:
        return ""

    tree = "\n".join(tree_lines)
    hint_parts: list[str] = []
    detected = [m for m in _STACK_MARKERS if (root / m).exists()]
    if detected:
        hint_parts.append("检测到：" + ", ".join(detected))
        # Pull a few dependency names so the planner knows the framework.
        try:
            pkg = root / "package.json"
            if pkg.exists():
                data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
                deps = list((data.get("dependencies") or {}).keys())
                if deps:
                    hint_parts.append("前端依赖(部分)：" + ", ".join(deps[:12]))
        except (ValueError, OSError):
            pass
        try:
            req = root / "requirements.txt"
            if req.exists():
                libs = [
                    line.strip().split("==")[0].split(">=")[0]
                    for line in req.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip() and not line.startswith("#")
                ]
                if libs:
                    hint_parts.append("Python依赖(部分)：" + ", ".join(libs[:12]))
        except OSError:
            pass
    hint = ("\n[技术栈线索] " + "；".join(hint_parts)) if hint_parts else ""
    return f"[项目结构]\n{tree}{hint}"


@dataclass(slots=True)
class PlanStep:
    id: int
    title: str
    goal: str
    deps: list[int] = field(default_factory=list)


def _topo_order(steps: list[PlanStep]) -> Optional[list[PlanStep]]:
    """Return steps ordered by dependency, or ``None`` if a cycle is detected."""
    by_id = {s.id: s for s in steps}
    ordered: list[PlanStep] = []
    visited: set[int] = set()
    temp: set[int] = set()

    def visit(sid: int) -> bool:
        if sid in visited:
            return True
        if sid in temp:
            return False  # cycle
        if sid not in by_id:
            return True  # dependency on an unknown/missing step is ignored
        temp.add(sid)
        for dep in by_id[sid].deps:
            if not visit(dep):
                return False
        temp.discard(sid)
        visited.add(sid)
        ordered.append(by_id[sid])
        return True

    for s in steps:
        if not visit(s.id):
            return None
    return ordered


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of *text*, stripping markdown fences.

    Models sometimes wrap ``{...}`` in ```json ... ``` blocks.  This helper
    unwraps those so ``json.loads`` gets a clean payload.
    """
    text = text.strip()
    # Strip ```json / ``` fences when present.
    m = re.match(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # If the model prefixed the JSON with a brief sentence, find the first '{'.
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    return text


def _parse_steps(raw_steps: list) -> tuple[list[PlanStep], str]:
    """Convert raw step dicts to :class:`PlanStep` list.

    Returns ``(steps, reject_reason)`` — *steps* is non-empty on success;
    *reject_reason* is a human-readable explanation when parsing fails.
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        return [], "模型未返回步骤列表（steps 字段为空或格式错误）"

    steps: list[PlanStep] = []
    for item in raw_steps:
        try:
            sid = int(item.get("id"))
            title = str(item.get("title") or f"步骤{sid}").strip()
            goal = str(item.get("goal") or "").strip()
            deps = [int(d) for d in (item.get("deps") or []) if str(d).isdigit()]
        except (TypeError, ValueError):
            continue
        if not title:
            continue
        steps.append(PlanStep(id=sid, title=title, goal=goal, deps=deps))

    # De-duplicate by id keeping first occurrence.
    seen: set[int] = set()
    unique: list[PlanStep] = []
    for s in steps:
        if s.id in seen:
            continue
        seen.add(s.id)
        unique.append(s)

    if not unique:
        return [], "模型返回的步骤无法解析（缺少有效 id/title）"
    return unique, ""


def _try_plan_once(
    task_description: str,
    model_name: str,
    api_key: str,
    base_url: str,
    max_subtasks: int,
    project_context: str,
) -> tuple[Optional[list[PlanStep]], str]:
    """Single planning attempt.  Returns ``(steps_or_None, error_reason)``."""
    system_prompt = (
        "你是一个资深软件架构师的助手。用户会给你一个软件开发任务，并可能附带"
        "项目结构。请把它拆解成若干个相互独立、可逐步验证、且能落到具体代码上的子步骤。\n"
        "只输出 JSON，不要输出任何解释文字。JSON 结构必须严格为：\n"
        "{\"steps\": [ {\"id\": 1, \"title\": \"步骤标题\", \"goal\": \"该步骤要达成的具体目标（写明要新建/修改的文件或模块与预期产物）\", "
        "\"deps\": []} ]}\n"
        "要求：\n"
        "1. id 从 1 开始连续递增，且每个 id 在 steps 中唯一；\n"
        "2. deps 是该步骤依赖的其他步骤 id 数组（空数组表示无依赖，可最先执行）；"
        "不要引用不存在的 id；\n"
        "3. 步骤数量控制在 1 到上限之间（简单任务 1 个步骤即可）；\n"
        "4. 每个步骤必须是「会产生代码改动」的工作：在 goal 中明确要新建或修改哪些"
        "文件/模块，以及完成后应有的产物（例如\"在 src/api/auth.py 新增登录接口，并补充单元测试\"）。"
        "不要拆出没有代码产物的纯调研/讨论步骤——若必须先了解现状，请把调研压缩进实现步骤"
        "（例如\"阅读 src/db.py 后，在其基础上新增 User 模型\"），而不是单独作为一个步骤；\n"
        "5. 步骤之间尽量解耦；当一个步骤的产物是下一步的输入（如先建模型再写接口）时，"
        "用 deps 表达依赖。不要出现循环依赖；\n"
        "6. 若项目结构中能看出相关文件，优先复用/扩展现有文件与约定，避免重复造轮子；\n"
        "7. 不要包含任何需要人工确认或外部系统审批才能继续的步骤。"
    )

    user_content = (
        f"请基于下面的项目结构拆解任务（若未提供结构，则按任务描述合理拆解）：\n\n"
        f"{project_context}\n\n【任务】\n{task_description}"
        if project_context else
        f"请拆解以下任务：\n{task_description}"
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": PLANNER_MAX_TOKENS,
    }
    if "api.deepseek.com" in base_url.lower():
        payload["thinking"] = {"type": "disabled"}

    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=PLANNER_REQUEST_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return None, f"网络请求失败：{exc}"
    except Exception as exc:
        return None, f"API 调用异常：{exc}"

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        return None, f"API 响应结构异常：{exc}"

    # Parse JSON — first try raw content, then try extracting from markdown.
    parsed = None
    parse_err = ""
    for text in (content, _extract_json(content)):
        try:
            parsed = json.loads(text)
            break
        except ValueError as e:
            parse_err = str(e)
    if parsed is None:
        return None, f"JSON 解析失败（{parse_err}）。原始返回：{content[:300]}"

    raw_steps = parsed.get("steps") or []
    steps, reason = _parse_steps(raw_steps)
    if not steps:
        return None, reason

    # Truncate to the agent's configured ceiling, preserving order.
    if len(steps) > max_subtasks:
        logger.info("Planner produced %d steps; truncating to %d", len(steps), max_subtasks)
        steps = steps[:max_subtasks]

    ordered = _topo_order(steps)
    if ordered is None:
        return None, "模型生成的步骤存在循环依赖，请重试"
    return ordered, ""


def plan_task(
    task_description: str,
    model_name: str,
    api_key: str,
    base_url: str,
    max_subtasks: int = 6,
    project_context: str = "",
) -> tuple[Optional[list[PlanStep]], str]:
    """Ask the model to decompose ``task_description`` into ordered subtasks.

    When ``project_context`` (produced by :func:`collect_project_context`) is
    supplied, the model decomposes the task against the *actual* project
    structure instead of from scratch, yielding steps that name concrete
    files/modules and avoid redundant discovery work.

    Returns ``(steps, error_reason)`` — *steps* is the dependency-ordered plan
    on success; *error_reason* is a human-readable explanation on failure (empty
    string on success).  The caller can surface *error_reason* to the user.
    """
    if not api_key or not base_url:
        return None, "未配置模型 API Key 或 Base URL"

    last_reason = ""
    for attempt in range(1, PLANNER_MAX_RETRIES + 1):
        steps, reason = _try_plan_once(
            task_description, model_name, api_key, base_url,
            max_subtasks, project_context,
        )
        if steps is not None:
            return steps, ""
        last_reason = reason
        if attempt < PLANNER_MAX_RETRIES:
            logger.warning(
                "Planner attempt %d/%d failed (%s); retrying…",
                attempt, PLANNER_MAX_RETRIES, reason,
            )
            time.sleep(1.2 * attempt)  # brief back-off

    logger.warning(
        "Planner exhausted %d retries. Last error: %s",
        PLANNER_MAX_RETRIES, last_reason,
    )
    return None, last_reason or "规划模型多次尝试均失败，请稍后重试"
