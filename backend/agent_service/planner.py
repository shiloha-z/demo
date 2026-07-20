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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Planning uses a thinking-disabled, non-reasoning call to stay fast and cheap.
PLANNER_REQUEST_TIMEOUT_SECONDS = 40


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


def plan_task(
    task_description: str,
    model_name: str,
    api_key: str,
    base_url: str,
    max_subtasks: int = 6,
) -> Optional[list[PlanStep]]:
    """Ask the model to decompose ``task_description`` into ordered subtasks.

    Returns a dependency-ordered list of :class:`PlanStep`, or ``None`` when the
    model could not produce a usable plan (caller should fall back).
    """
    if not api_key or not base_url:
        return None

    system_prompt = (
        "你是一个任务规划助手。用户会给你一个软件开发任务，你需要把它拆解成"
        "若干个相互独立、可逐步验证的子步骤。\n"
        "只输出 JSON，不要输出任何解释文字。JSON 结构必须严格为：\n"
        "{\"steps\": [ {\"id\": 1, \"title\": \"步骤标题\", \"goal\": \"该步骤要达成的具体目标\", "
        "\"deps\": []} ]}\n"
        "要求：\n"
        "1. id 从 1 开始连续递增，且每个 id 在 steps 中唯一；\n"
        "2. deps 是该步骤依赖的其他步骤 id 数组（空数组表示无依赖，可最先执行）；"
        "不要引用不存在的 id；\n"
        "3. 步骤数量控制在 2 到上限之间，先调研/理解现状，再实现，最后自检；\n"
        "4. 每个步骤都应是 Agent 可以通过写文件、运行命令来完成的真实工作，不要拆解成"
        "过度细碎的元步骤。\n"
        "5. 不要包含任何需要人工确认或外部系统审批才能继续的步骤。"
    )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请拆解以下任务：\n{task_description}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 2048,
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
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        raw_steps = parsed.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            logger.warning("Planner returned no steps; falling back to default pipeline")
            return None

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

        if len(unique) < 2:
            logger.warning("Planner produced <2 usable steps; falling back")
            return None

        # Truncate to the agent's configured ceiling, preserving order.
        if len(unique) > max_subtasks:
            logger.info("Planner produced %d steps; truncating to %d", len(unique), max_subtasks)
            unique = unique[:max_subtasks]

        ordered = _topo_order(unique)
        if ordered is None:
            logger.warning("Planner produced a dependency cycle; falling back")
            return None
        return ordered
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError, IndexError) as exc:
        logger.warning("Planning LLM call failed (%s); falling back to default pipeline", exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Unexpected planning error (%s); falling back", exc)
        return None
