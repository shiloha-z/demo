"""基于变更风险的动态审批评分服务。

在 Agent 完成代码生成、提交 commit 之后、人工审批之前计算风险评分。
评分结果驱动 ReviewRound 的 required_approvals 与
require_security_reviewer，实现"基于风险的动态审批"。

风险因子（参考银行变更管理实践）：
  - 修改文件数量
  - 代码变更行数
  - 是否涉及认证/权限模块
  - 是否涉及交易、账户或客户信息
  - 是否修改数据库结构（DDL）
  - 是否新增外部依赖
  - 是否发现高危安全问题（来自质量门禁结果）
  - 是否缺少自动化测试
  - 是否涉及加密/密钥操作

风险等级与审批策略：
  - 低风险 (score < MEDIUM):   1 人审批 + 自动检查通过
  - 中风险 (MEDIUM <= s < HIGH): 2 人审批
  - 高风险 (HIGH <= s < CRITICAL): 2 人审批 + 至少 1 名安全复核人
  - 严重风险 (s >= CRITICAL):    禁止自动合并，必须线下确认后由管理员强制推进
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    Project,
    ProjectMember,
    ProjectRole,
    QualityGateRun,
    Review,
    ReviewRound,
    ReviewVote,
    RiskAssessment,
    Task,
)
from app.services import git_service as git

logger = logging.getLogger(__name__)


# ── 命中即加分的高危关键词（按文件路径与内容） ────────────────────────
SENSITIVE_PATH_KEYWORDS = {
    "auth": ("认证/权限模块", 15),
    "login": ("认证/权限模块", 15),
    "password": ("认证/权限模块", 12),
    "token": ("认证/权限模块", 10),
    "session": ("认证/权限模块", 8),
    "permission": ("权限校验", 12),
    "rbac": ("权限校验", 12),
    "acl": ("权限校验", 10),
    "transfer": ("交易/转账", 18),
    "payment": ("交易/转账", 18),
    "transaction": ("交易/转账", 15),
    "account": ("账户信息", 15),
    "customer": ("客户信息", 12),
    "balance": ("账户余额", 15),
    "card": ("银行卡", 12),
    "idcard": ("身份证号", 12),
    "id_number": ("身份证号", 12),
    "crypto": ("加密/密钥", 12),
    "cipher": ("加密/密钥", 10),
    "secret": ("密钥管理", 10),
    "key": ("密钥管理", 6),
    "encrypt": ("加密操作", 10),
    "decrypt": ("加密操作", 10),
    "sign": ("签名验签", 8),
}

# DDL 关键词（修改数据库结构）
DDL_PATTERNS = (
    re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bADD\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
)

# 依赖清单文件名
DEPENDENCY_MANIFESTS = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml",
}

# 测试文件特征
TEST_FILE_PATTERNS = (
    re.compile(r"test_.*\.py$", re.IGNORECASE),
    re.compile(r".*_test\.py$", re.IGNORECASE),
    re.compile(r".*\.test\.(js|ts|jsx|tsx)$", re.IGNORECASE),
    re.compile(r".*\.spec\.(js|ts|jsx|tsx)$", re.IGNORECASE),
    re.compile(r"/tests?/", re.IGNORECASE),
    re.compile(r"/__tests__/", re.IGNORECASE),
)

# 高危质量门禁检查项（命中即升级风险等级）
HIGH_RISK_GATE_KEYS = {"secret_scan", "bank_policy", "dependency_audit"}


@dataclass
class RiskFactor:
    key: str
    label: str
    weight: int
    hit: bool
    detail: str = ""


@dataclass
class RiskResult:
    score: int
    level: str                      # low / medium / high / critical
    factors: list[RiskFactor] = field(default_factory=list)
    recommended_approvals: int = 1
    require_security_reviewer: bool = False
    auto_merge_blocked: bool = False

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level,
            "factors": [asdict(f) for f in self.factors],
            "recommended_approvals": self.recommended_approvals,
            "require_security_reviewer": self.require_security_reviewer,
            "auto_merge_blocked": self.auto_merge_blocked,
        }


def _classify_level(score: int) -> str:
    if score >= settings.RISK_SCORE_THRESHOLD_CRITICAL:
        return "critical"
    if score >= settings.RISK_SCORE_THRESHOLD_HIGH:
        return "high"
    if score >= settings.RISK_SCORE_THRESHOLD_MEDIUM:
        return "medium"
    return "low"


def _policy_for_level(level: str) -> tuple[int, bool, bool]:
    """Return (recommended_approvals, require_security_reviewer, auto_merge_blocked)."""
    if level == "critical":
        # 严重风险：禁止自动合并，需管理员线下确认后强制推进。
        # 仍要求 2 人 + 安全复核人，但 auto_merge_blocked=True 会阻止常规投票路径。
        return (2, True, True)
    if level == "high":
        return (2, True, False)
    if level == "medium":
        return (2, False, False)
    return (1, False, False)


def _scan_sensitive_paths(changed_files: list[str]) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    hit_keywords: dict[str, list[str]] = {}
    for relative in changed_files:
        lowered = relative.lower()
        for keyword, (label, weight) in SENSITIVE_PATH_KEYWORDS.items():
            if keyword in lowered:
                hit_keywords.setdefault(label, []).append(relative)
    for label, files in hit_keywords.items():
        weight = max(
            w for k, (lbl, w) in SENSITIVE_PATH_KEYWORDS.items() if lbl == label
        )
        factors.append(RiskFactor(
            key=f"sensitive_path_{label}",
            label=f"涉及{label}",
            weight=weight,
            hit=True,
            detail=f"命中文件：{', '.join(sorted(set(files))[:5])}",
        ))
    return factors


def _scan_ddl(workspace: str, changed_files: list[str]) -> RiskFactor:
    from pathlib import Path
    hits: list[str] = []
    root = Path(workspace).resolve()
    for relative in changed_files:
        if not relative.lower().endswith((".sql", ".py", ".js", ".ts", ".java")):
            continue
        path = (root / relative).resolve()
        try:
            if not path.is_relative_to(root) or not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in DDL_PATTERNS:
            if pattern.search(content):
                hits.append(relative)
                break
    return RiskFactor(
        key="ddl_change",
        label="修改数据库结构",
        weight=20,
        hit=bool(hits),
        detail=f"命中文件：{', '.join(sorted(set(hits))[:5])}" if hits else "",
    )


def _scan_new_dependencies(changed_files: list[str]) -> RiskFactor:
    new_dep = any(
        any(manifest in f.lower() for manifest in DEPENDENCY_MANIFESTS)
        for f in changed_files
    )
    return RiskFactor(
        key="new_dependency",
        label="新增/修改外部依赖",
        weight=10,
        hit=new_dep,
        detail="修改了依赖清单文件，可能引入供应链风险" if new_dep else "",
    )


def _scan_missing_tests(changed_files: list[str]) -> RiskFactor:
    has_test = any(p.search(f) for f in changed_files for p in TEST_FILE_PATTERNS)
    has_source = any(
        f.lower().endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go"))
        and not any(p.search(f) for p in TEST_FILE_PATTERNS)
        for f in changed_files
    )
    missing = has_source and not has_test
    return RiskFactor(
        key="missing_tests",
        label="缺少自动化测试",
        weight=8,
        hit=missing,
        detail="本次变更包含源码但未包含测试文件" if missing else "",
    )


def _scale_factors(changed_files: list[str], diff_lines: int) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    file_count = len(changed_files)
    if file_count >= 20:
        factors.append(RiskFactor("file_count_large", "修改文件数 ≥ 20", 12, True, f"共 {file_count} 个文件"))
    elif file_count >= 10:
        factors.append(RiskFactor("file_count_medium", "修改文件数 ≥ 10", 6, True, f"共 {file_count} 个文件"))

    if diff_lines >= 500:
        factors.append(RiskFactor("diff_huge", "变更行数 ≥ 500", 12, True, f"共 {diff_lines} 行"))
    elif diff_lines >= 200:
        factors.append(RiskFactor("diff_large", "变更行数 ≥ 200", 6, True, f"共 {diff_lines} 行"))
    return factors


def _gate_risk_factor(latest_gate: QualityGateRun | None) -> RiskFactor:
    """Inspect the latest quality-gate run for high-risk findings."""
    if not latest_gate or latest_gate.status != "failed":
        return RiskFactor("gate_high_risk", "高危安全问题", 0, False)
    try:
        checks = json.loads(latest_gate.results_json or "[]")
    except (TypeError, json.JSONDecodeError):
        checks = []
    high_hits: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("status") != "failed":
            continue
        if check.get("key") in HIGH_RISK_GATE_KEYS:
            high_hits.append(check.get("label") or check.get("key") or "未知")
    return RiskFactor(
        "gate_high_risk",
        "高危安全问题",
        25,
        bool(high_hits),
        f"门禁失败项：{', '.join(high_hits)}" if high_hits else "",
    )


def assess_task_risk(
    db: Session,
    *,
    task: Task,
    review: Review | None = None,
    workspace: str | None = None,
    commit_hash: str = "",
    changed_files: list[str] | None = None,
    diff_lines: int | None = None,
) -> RiskResult:
    """Compute the risk score for a task's pending review.

    当 review 已生成、workspace 可用时，会读取实际变更文件和门禁结果
    做精确评分；任务创建阶段（无 review/workspace）则退化为基于任务
    标题和描述的初步评分，用于在 UI 上提前提示风险等级。
    """
    factors: list[RiskFactor] = []

    # 精确模式：基于实际变更
    if workspace and changed_files is not None:
        factors.extend(_scan_sensitive_paths(changed_files))
        factors.append(_scan_ddl(workspace, changed_files))
        factors.append(_scan_new_dependencies(changed_files))
        factors.append(_scan_missing_tests(changed_files))
        if diff_lines is None:
            diff_lines = 0
        factors.extend(_scale_factors(changed_files, diff_lines))

        # 关联最新门禁结果
        gate_q = db.query(QualityGateRun).filter(QualityGateRun.task_id == task.id)
        if review is not None:
            gate_q = gate_q.filter(QualityGateRun.review_id == review.id)
        latest_gate = gate_q.order_by(QualityGateRun.id.desc()).first()
        factors.append(_gate_risk_factor(latest_gate))
    else:
        # 初步模式：基于任务文本
        text = f"{task.title} {task.description or ''}".lower()
        for keyword, (label, weight) in SENSITIVE_PATH_KEYWORDS.items():
            if keyword in text:
                factors.append(RiskFactor(
                    key=f"task_text_{label}",
                    label=f"任务涉及{label}",
                    weight=max(5, weight // 2),  # 初步评分减半
                    hit=True,
                    detail=f"任务描述命中关键词：{keyword}",
                ))

    score = sum(f.weight for f in factors if f.hit)
    level = _classify_level(score)
    recommended_approvals, require_sec, block_merge = _policy_for_level(level)

    # 高风险任务若项目内无安全复核人，则降级为强制 2 人 + 警告
    if require_sec:
        sec_reviewers = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == task.project_id,
                ProjectMember.role == ProjectRole.SECURITY_REVIEWER,
            )
            .count()
        )
        if sec_reviewers == 0:
            # 仍标记 require_security_reviewer=True 以便前端提示配置安全复核人，
            # 但不阻塞流程（避免无人项目卡死）。
            factors.append(RiskFactor(
                "no_security_reviewer",
                "缺少安全复核人",
                5,
                True,
                "高风险变更但项目未配置安全复核人，建议补充",
            ))
            score += 5
            level = _classify_level(score)
            recommended_approvals, require_sec, block_merge = _policy_for_level(level)

    return RiskResult(
        score=score,
        level=level,
        factors=factors,
        recommended_approvals=recommended_approvals,
        require_security_reviewer=require_sec,
        auto_merge_blocked=block_merge,
    )


def persist_assessment(
    db: Session,
    *,
    task: Task,
    review: Review | None,
    result: RiskResult,
    commit_hash: str = "",
) -> RiskAssessment:
    """Persist a risk assessment and return the ORM record."""
    assessment = RiskAssessment(
        task_id=task.id,
        review_id=review.id if review else None,
        commit_hash=commit_hash,
        risk_score=result.score,
        risk_level=result.level,
        factors_json=json.dumps(result.to_dict()["factors"], ensure_ascii=False),
        recommended_approvals=result.recommended_approvals,
        require_security_reviewer=result.require_security_reviewer,
        auto_merge_blocked=result.auto_merge_blocked,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def apply_to_review_round(
    db: Session,
    *,
    task: Task,
    review: Review,
    round_: ReviewRound,
    result: RiskResult,
) -> ReviewRound:
    """Apply the risk result to an existing ReviewRound (before voting starts).

    必须在投票开始前调用：投票开始后 ReviewRound 不可修改。
    """
    if db.query(ReviewVote).filter(ReviewVote.review_id == review.id).first():
        # 投票已开始，不能修改策略
        return round_

    round_.risk_level = result.level
    round_.risk_score = result.score
    round_.require_security_reviewer = result.require_security_reviewer
    round_.required_approvals = max(round_.required_approvals, result.recommended_approvals)
    db.commit()
    return round_


def latest_assessment(task_id: int, db: Session) -> RiskAssessment | None:
    return (
        db.query(RiskAssessment)
        .filter(RiskAssessment.task_id == task_id)
        .order_by(RiskAssessment.id.desc())
        .first()
    )


def latest_assessment_for_review(review_id: int, db: Session) -> RiskAssessment | None:
    return (
        db.query(RiskAssessment)
        .filter(RiskAssessment.review_id == review_id)
        .order_by(RiskAssessment.id.desc())
        .first()
    )
