"""Risk Dashboard — bank-defence analytics endpoint.

Provides a single ``GET /api/risk-dashboard?project_id=<optional>`` that
aggregates 10 KPIs across the user's accessible projects.  Six are powered
by live queries; four are served as ``planned`` placeholders so the dashboard
looks complete during defence presentations while honestly signalling which
instrumentation is still to be added.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import (
    Project,
    ProjectMember,
    QualityGateRun,
    Review,
    ReviewVote,
    Task,
    User,
)

router = APIRouter(prefix="/api", tags=["Risk Dashboard"])

# ── Schemas ───────────────────────────────────────────────────────────────


class RiskMetric(BaseModel):
    value: int | float | str | None = None
    label: str = ""
    unit: str = ""            # e.g. "%", "次", "小时", "个"
    status: str = "active"    # "active" | "planned"
    detail: dict | None = None  # optional breakdown (used by risk-severity KPI)


class RiskDashboardResponse(BaseModel):
    project_id: int | None = None
    tasks_this_week: RiskMetric
    ai_code_ratio: RiskMetric
    avg_task_time: RiskMetric
    avg_review_time: RiskMetric
    risk_severity_breakdown: RiskMetric
    gate_blocks: RiskMetric
    first_pass_rate: RiskMetric
    repeat_issue_reduction: RiskMetric
    rollback_count: RiskMetric
    model_cost: RiskMetric


# ── Helpers ───────────────────────────────────────────────────────────────


def _planned(label: str, unit: str) -> RiskMetric:
    """Return a placeholder metric for dashboard cards that lack data sources."""
    return RiskMetric(value=None, label=label, unit=unit, status="planned")


def _member_project_ids(user: User, db: Session) -> set[int]:
    """Project IDs the user can access (owner or member)."""
    rows = (
        db.query(Project.id)
        .outerjoin(
            ProjectMember,
            Project.id == ProjectMember.project_id,
        )
        .filter(
            (Project.owner_id == user.id) | (ProjectMember.user_id == user.id)
        )
        .all()
    )
    return {row[0] for row in rows}


def _check_project_access(project_id: int, user: User, db: Session) -> None:
    """Raise 404/403 if the user cannot access the project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == user.id:
        return
    member = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="只有项目成员才能查看风险仪表盘")


# ── Metric aggregators ────────────────────────────────────────────────────


def _tasks_this_week(project_ids: set[int], db: Session) -> RiskMetric:
    week_start = datetime.now(timezone.utc) - timedelta(
        days=datetime.now(timezone.utc).weekday()
    )
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    q = db.query(func.count(Task.id)).filter(Task.created_at >= week_start)
    if project_ids:
        q = q.filter(Task.project_id.in_(project_ids))
    return RiskMetric(value=q.scalar() or 0, label="本周任务数量", unit="个")


def _avg_task_time(project_ids: set[int], db: Session) -> RiskMetric:
    """Average wall-clock hours from creation to completion.

    Uses SQLite ``julianday()`` which returns fractional days.  When migrating
    to PostgreSQL replace with ``extract(epoch FROM …) / 3600``.
    """
    q = db.query(
        func.avg(func.julianday(Task.completed_at) - func.julianday(Task.created_at))
    ).filter(Task.completed_at.isnot(None))
    if project_ids:
        q = q.filter(Task.project_id.in_(project_ids))
    avg_days = q.scalar()
    avg_hours = round(avg_days * 24, 1) if avg_days is not None else None
    return RiskMetric(value=avg_hours, label="平均任务处理时间", unit="小时")


def _avg_review_time(project_ids: set[int], db: Session) -> RiskMetric:
    """Average wall-clock hours from review creation to first human vote."""
    q = db.query(
        func.avg(
            func.julianday(ReviewVote.created_at) - func.julianday(Review.created_at)
        )
    ).join(Review, ReviewVote.review_id == Review.id)
    if project_ids:
        q = q.filter(Review.project_id.in_(project_ids))
    avg_days = q.scalar()
    avg_hours = round(avg_days * 24, 1) if avg_days is not None else None
    return RiskMetric(value=avg_hours, label="平均人工审查时间", unit="小时")


def _risk_severity_breakdown(project_ids: set[int], db: Session) -> RiskMetric:
    """Parse QualityGateRun results_json and classify failures by severity.

    Severity taxonomy (banking compliance aligned):
      - 高风险: secret_scan, bank_policy, dependency_audit
      - 中风险: static_analysis, unit_tests, coverage
      - 低风险: style
    """
    q = db.query(QualityGateRun).filter(QualityGateRun.status == "failed")
    if project_ids:
        q = q.filter(
            QualityGateRun.task_id.in_(
                db.query(Task.id).filter(Task.project_id.in_(project_ids))
            )
        )
    # Only scan recent runs to bound parse cost.
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    q = q.filter(QualityGateRun.started_at >= cutoff)

    high_keys = {"secret_scan", "bank_policy", "dependency_audit"}
    med_keys = {"static_analysis", "unit_tests", "coverage"}
    low_keys = {"style"}

    high = med = low = 0
    failed_run_count = 0
    for run in q.all():
        try:
            checks = json.loads(run.results_json or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        run_findings = 0
        for check in checks:
            if not isinstance(check, dict):
                continue
            if check.get("status") != "failed":
                continue
            findings = check.get("findings", 0) or 0
            key = check.get("key", "")
            if key in high_keys:
                high += findings
            elif key in med_keys:
                med += findings
            elif key in low_keys:
                low += findings
            run_findings += findings
        if run_findings:
            failed_run_count += 1

    return RiskMetric(
        value=failed_run_count,
        label="高/中/低风险问题",
        unit="次",
        detail={"high": high, "medium": med, "low": low},
    )


def _gate_blocks(project_ids: set[int], db: Session) -> RiskMetric:
    q = db.query(func.count(QualityGateRun.id)).filter(
        QualityGateRun.status == "failed"
    )
    if project_ids:
        q = q.filter(
            QualityGateRun.task_id.in_(
                db.query(Task.id).filter(Task.project_id.in_(project_ids))
            )
        )
    return RiskMetric(value=q.scalar() or 0, label="自动门禁拦截次数", unit="次")


def _first_pass_rate(project_ids: set[int], db: Session) -> RiskMetric:
    """Share of approved reviews whose task was never rejected.

    *First pass* means the task's review was approved without the task ever
    having any rejected review — i.e. the change got through in one shot.
    """
    approved_q = db.query(func.count(Review.id)).filter(
        Review.status == "approved"
    )
    rejected_sub = db.query(Review.task_id).filter(Review.status == "rejected")
    if project_ids:
        approved_q = approved_q.filter(Review.project_id.in_(project_ids))
        rejected_sub = rejected_sub.filter(Review.project_id.in_(project_ids))

    total = approved_q.scalar() or 0
    first_pass = (
        approved_q.filter(
            ~Review.task_id.in_(select(rejected_sub.subquery().c.task_id))
        ).scalar() or 0
    )
    rate = round(first_pass / total * 100, 1) if total else None
    return RiskMetric(
        value=rate,
        label="首次通过率",
        unit="%",
        detail={"first_pass": first_pass, "total": total},
    )


# ── Endpoint ──────────────────────────────────────────────────────────────


@router.get("/risk-dashboard", response_model=RiskDashboardResponse)
def get_risk_dashboard(
    project_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if project_id is not None:
        _check_project_access(project_id, user, db)
        project_ids = {project_id}
    else:
        project_ids = _member_project_ids(user, db)

    return RiskDashboardResponse(
        project_id=project_id,
        tasks_this_week=_tasks_this_week(project_ids, db),
        ai_code_ratio=_planned("AI 生成代码占比", "%"),
        avg_task_time=_avg_task_time(project_ids, db),
        avg_review_time=_avg_review_time(project_ids, db),
        risk_severity_breakdown=_risk_severity_breakdown(project_ids, db),
        gate_blocks=_gate_blocks(project_ids, db),
        first_pass_rate=_first_pass_rate(project_ids, db),
        repeat_issue_reduction=_planned("驳回后重复问题下降率", "%"),
        rollback_count=_planned("版本回退次数", "次"),
        model_cost=_planned("模型调用量与估算成本", "次/元"),
    )
