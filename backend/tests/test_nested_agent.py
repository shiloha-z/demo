"""Tests for the nested-agent (task planning) feature.

These focus on the safety-critical behaviour called out in the design: the
planner must never raise (it returns ``None`` on any failure so the caller
falls back to the default pipeline), and it must return dependency-ordered,
valid steps.
"""

import json
import urllib.error
from unittest import mock

import pytest

from agent_service.planner import plan_task, _topo_order


GOOD_PAYLOAD = {
    "steps": [
        {"id": 1, "title": "调研现状", "goal": "理解现有代码", "deps": []},
        {"id": 2, "title": "实现功能", "goal": "编写核心逻辑", "deps": [1]},
        {"id": 3, "title": "补充测试", "goal": "写单测", "deps": [2]},
    ]
}


def _fake_response(payload: dict) -> bytes:
    return json.dumps({
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }).encode("utf-8")


def test_plan_task_returns_ordered_steps_on_success():
    body = _fake_response(GOOD_PAYLOAD)
    with mock.patch("urllib.request.urlopen", return_value=mock.MagicMock(
        read=lambda: body, __enter__=lambda self: self, __exit__=lambda *a: False
    )):
        steps = plan_task("实现一个登录接口", "deepseek-chat", "key", "https://api.deepseek.com")
    assert steps is not None
    # Dependency order must be preserved: 1 -> 2 -> 3
    assert [s.id for s in steps] == [1, 2, 3]


def test_plan_task_returns_none_on_malformed_json():
    body = b'{"choices":[{"message":{"content":"not json at all"}}]}'
    with mock.patch("urllib.request.urlopen", return_value=mock.MagicMock(
        read=lambda: body, __enter__=lambda self: self, __exit__=lambda *a: False
    )):
        steps = plan_task("task", "deepseek-chat", "key", "https://api.deepseek.com")
    assert steps is None


def test_plan_task_returns_none_on_network_error():
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        steps = plan_task("task", "deepseek-chat", "key", "https://api.deepseek.com")
    assert steps is None


def test_plan_task_returns_none_without_credentials():
    # Missing API key / base_url must short-circuit without a network call.
    with mock.patch("urllib.request.urlopen") as m:
        assert plan_task("task", "deepseek-chat", "", "https://api.deepseek.com") is None
        assert plan_task("task", "deepseek-chat", "key", "") is None
        m.assert_not_called()


def test_plan_task_truncates_to_max_subtasks():
    many = {"steps": [{"id": i, "title": f"s{i}", "goal": "g", "deps": []} for i in range(1, 10)]}
    body = _fake_response(many)
    with mock.patch("urllib.request.urlopen", return_value=mock.MagicMock(
        read=lambda: body, __enter__=lambda self: self, __exit__=lambda *a: False
    )):
        steps = plan_task("task", "deepseek-chat", "key", "https://api.deepseek.com", max_subtasks=3)
    assert len(steps) == 3


def test_topo_order_detects_cycle():
    from agent_service.planner import PlanStep
    a = PlanStep(id=1, title="a", goal="", deps=[2])
    b = PlanStep(id=2, title="b", goal="", deps=[1])
    assert _topo_order([a, b]) is None


def test_topo_order_ignores_unknown_deps():
    from agent_service.planner import PlanStep
    a = PlanStep(id=1, title="a", goal="", deps=[99])
    ordered = _topo_order([a])
    assert ordered is not None and ordered[0].id == 1
