"""Audit action registry — the single source of truth for audit actions.

Extensibility:
  Adding a new kind of audit event only requires TWO edits:
    1. Add the value to `AuditAction` (in models.models).
    2. Add one entry to `ACTION_REGISTRY` below.
  The frontend renders badges / filter chips purely from this registry
  (served via GET /api/audit/actions), so no frontend changes are needed.

Each entry maps an action value → metadata:
  - label:  human-readable Chinese name (shown on badges & filters)
  - group:  logical grouping for color-coding & grouping UI
            (task / agent / review / member / config / merge / system)
"""

from app.models.models import AuditAction

# Group → (display label, CSS-ish color token used by the frontend to pick a class)
ACTION_GROUPS: dict[str, dict] = {
    "task":   {"label": "任务",   "token": "task"},
    "agent":  {"label": "AI",     "token": "agent"},
    "review": {"label": "审查",   "token": "review"},
    "member": {"label": "成员",   "token": "member"},
    "config": {"label": "配置",   "token": "config"},
    "merge":  {"label": "合并",   "token": "merge"},
    "system": {"label": "系统",   "token": "system"},
}

# action value → {label, group}
ACTION_REGISTRY: dict[str, dict] = {
    # ── 任务生命周期 ──
    AuditAction.TASK_CREATE.value:    {"label": "创建任务", "group": "task"},
    AuditAction.TASK_START.value:     {"label": "启动任务", "group": "task"},
    AuditAction.TASK_STOP.value:      {"label": "暂停任务", "group": "task"},
    AuditAction.TASK_RESUME.value:    {"label": "恢复任务", "group": "task"},
    AuditAction.TASK_ARCHIVE.value:   {"label": "归档任务", "group": "task"},
    AuditAction.TASK_DELETE.value:    {"label": "删除任务", "group": "task"},
    AuditAction.AGENT_DISPATCH.value: {"label": "派发 AI",  "group": "agent"},
    # ── 审查投票 ──
    AuditAction.REVIEW_VOTE.value:    {"label": "投票",     "group": "review"},
    AuditAction.REVIEW_APPROVE.value: {"label": "审查通过", "group": "review"},
    AuditAction.REVIEW_REJECT.value:  {"label": "审查驳回", "group": "review"},
    AuditAction.REVIEW_CLOSE.value:   {"label": "关闭审查", "group": "review"},
    # ── 协作与成员 ──
    AuditAction.TRANSFER_OWNER.value: {"label": "转让所有权", "group": "member"},
    AuditAction.MEMBER_ADD.value:     {"label": "新增成员", "group": "member"},
    AuditAction.MEMBER_REMOVE.value:  {"label": "移除成员", "group": "member"},
    AuditAction.JOIN_APPROVE.value:   {"label": "批准加入", "group": "member"},
    AuditAction.JOIN_REJECT.value:    {"label": "驳回加入", "group": "member"},
    # ── 配置 ──
    AuditAction.CONFIG_UPDATE.value:  {"label": "配置变更", "group": "config"},
    # ── 确定性质量门禁 ──
    AuditAction.QUALITY_GATE_START.value: {"label": "门禁开始", "group": "review"},
    AuditAction.QUALITY_GATE_PASS.value:  {"label": "门禁通过", "group": "review"},
    AuditAction.QUALITY_GATE_FAIL.value:  {"label": "门禁拦截", "group": "review"},
    # ── 对项目的影响（AI 自动行为）──
    AuditAction.MERGE_DONE.value:             {"label": "合并完成", "group": "merge"},
    AuditAction.CONFLICT_AUTO_RESOLVED.value: {"label": "冲突自动解决", "group": "merge"},
}


def resolve_action(action_value: str) -> dict:
    """Return the registry metadata for an action, with safe fallback so an
    action added to the enum but not yet registry-ed still renders gracefully.
    """
    return ACTION_REGISTRY.get(action_value, {"label": action_value, "group": "system"})
