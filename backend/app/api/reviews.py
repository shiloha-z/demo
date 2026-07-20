import json
from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.pagination import paginate
from app.core.permissions import require_project_admin, require_project_member
from app.models.models import User, QualityGateRun, Review, ReviewStatus, ReviewRound, ReviewReviewer, ReviewVote, ProjectMember, Task, TaskStatus, Version, Agent, AgentStatus
from app.services import git_service as git
from app.services import quality_gate_service as quality_gates
from app.services.audit_service import record as audit_record
from app.models.models import AuditAction, AuditActorType
from app.core.config import settings

# Lazy import — memory_service may fail if chromadb not installed
try:
    from app.services import memory_service as mem
except ImportError:
    mem = None

router = APIRouter(prefix="/api", tags=["Reviews"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    id: int
    task_id: int
    project_id: int
    diff_content: str
    agent_review_summary: str
    status: str
    human_feedback: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class RejectRequest(BaseModel):
    feedback: str


class ReviewersRequest(BaseModel):
    reviewer_ids: list[int] = Field(..., min_length=1)
    required_approvals: int = Field(..., ge=1)
    veto_on_reject: bool = True


class VoteRequest(BaseModel):
    decision: str
    comment: str = ""


def _ensure_vote_round(review: Review, db: Session) -> ReviewRound:
    """Create a usable default voting round for reviews created before voting."""
    round_ = db.query(ReviewRound).filter(ReviewRound.review_id == review.id).first()
    if round_:
        return round_
    member_ids = [row[0] for row in db.query(ProjectMember.user_id).filter(
        ProjectMember.project_id == review.project_id
    ).all()]
    round_ = ReviewRound(
        review_id=review.id,
        required_approvals=max(1, min(2, len(member_ids))),
    )
    db.add(round_)
    try:
        db.flush()
    except Exception:
        db.rollback()
        return db.query(ReviewRound).filter(ReviewRound.review_id == review.id).first()
    db.add_all([ReviewReviewer(review_id=review.id, user_id=user_id) for user_id in member_ids])
    db.commit()
    return round_


def _vote_summary(review: Review, db: Session) -> dict:
    round_ = _ensure_vote_round(review, db)
    reviewers = db.query(ReviewReviewer, User).join(
        User, ReviewReviewer.user_id == User.id
    ).filter(ReviewReviewer.review_id == review.id).all()
    votes = db.query(ReviewVote).filter(ReviewVote.review_id == review.id).all()
    vote_by_user = {vote.user_id: vote for vote in votes}
    return {
        "required_approvals": round_.required_approvals,
        "veto_on_reject": round_.veto_on_reject,
        "approve_count": sum(v.decision == "approve" for v in votes),
        "reject_count": sum(v.decision == "reject" for v in votes),
        "reviewers": [{
            "user_id": reviewer.user_id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "vote": vote_by_user[reviewer.user_id].decision if reviewer.user_id in vote_by_user else None,
            "comment": vote_by_user[reviewer.user_id].comment if reviewer.user_id in vote_by_user else "",
        } for reviewer, user in reviewers],
    }


def _latest_quality_gate(review_id: int, db: Session) -> QualityGateRun | None:
    return db.query(QualityGateRun).filter(
        QualityGateRun.review_id == review_id
    ).order_by(QualityGateRun.id.desc()).first()


def _require_passed_quality_gate(review: Review, db: Session) -> QualityGateRun:
    run = _latest_quality_gate(review.id, db)

    # When the quality-gate subsystem is disabled, skip the required-check
    # logic entirely.  Synthesise a dummy "passed" record so that callers
    # which read .commit_hash / .id still work.
    if not settings.QUALITY_GATE_ENABLED:
        return type(
            "_SyntheticGate",
            (),
            {"status": "passed", "commit_hash": "", "id": None},
        )()

    if not run or run.status != "passed":
        raise HTTPException(
            status_code=409,
            detail="确定性检查尚未全部通过，不能批准；请先按失败项打回 Agent 修改",
        )
    task = db.get(Task, review.task_id)
    if not task or not task.worktree_path:
        raise HTTPException(status_code=409, detail="任务工作区不存在，无法验证门禁版本")
    current_commit = git.head_commit(task.worktree_path)
    if not run.commit_hash or current_commit != run.commit_hash:
        raise HTTPException(
            status_code=409,
            detail="门禁通过后的代码版本已发生变化，必须重新执行 Agent 和确定性检查",
        )
    return run


def _queue_review_merge(review: Review, task: Task, db: Session) -> dict:
    """Persist approval first, then let the project merge worker serialize it."""
    gate_run = _require_passed_quality_gate(review, db)
    review.status = ReviewStatus.APPROVED
    task.status = TaskStatus.MERGE_QUEUED
    task.merge_queued_at = datetime.now(timezone.utc)
    task.merge_error = ""
    db.commit()

    from app.api.ws import broadcast_sync
    broadcast_sync("review_update", {
        "id": review.id, "task_id": review.task_id,
        "project_id": review.project_id, "status": "approved",
    })
    broadcast_sync("task_update", {
        "id": task.id, "project_id": task.project_id, "status": "merge_queued",
    })
    # The approval has already been persisted above.  A temporary in-process
    # scheduling failure must not turn a successful approval into a 500; the
    # startup recovery hook will pick up this persisted queue item on restart.
    try:
        from app.services.execution_service import enqueue_merge
        enqueue_merge(task.id)
    except Exception:
        logger.exception("Failed to wake merge queue for task %s", task.id)

    # Audit: 审查达到法定票数，自动批准并入合并队列。
    audit_record(
        action=AuditAction.REVIEW_APPROVE,
        actor_type=AuditActorType.SYSTEM,
        project_id=review.project_id,
        task_id=task.id,
        target_type="review",
        target_id=review.id,
        intent="审查达到法定批准票数",
        payload={
            "required_approvals": _ensure_vote_round(review, db).required_approvals,
            "quality_gate_run_id": gate_run.id,
            "quality_gate_commit": gate_run.commit_hash,
        },
    )
    return {"message": "Approved and queued for merge"}


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_member(project_id, user, db)
    q = db.query(Review).filter(Review.project_id == project_id).order_by(Review.id.desc())
    reviews, paging = paginate(q, page, page_size)
    return {"items": [ReviewResponse.model_validate(r) for r in reviews], **paging}


@router.get("/reviews/pending-count")
def pending_review_count(
    project_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return count of pending reviews, optionally scoped to a project."""
    q = db.query(Review).filter(Review.status == ReviewStatus.PENDING)
    if project_id is not None:
        q = q.filter(Review.project_id == project_id)
    return {"count": q.count()}


@router.get("/reviews/{review_id}", response_model=ReviewResponse)
def get_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_member(review.project_id, user, db)
    return ReviewResponse.model_validate(review)


@router.get("/reviews/{review_id}/votes")
def get_review_votes(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_member(review.project_id, user, db)
    return _vote_summary(review, db)


@router.get("/reviews/{review_id}/quality-gate")
def get_review_quality_gate(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_member(review.project_id, user, db)
    run = _latest_quality_gate(review.id, db)
    if not run:
        return None
    try:
        checks = json.loads(run.results_json or "[]")
    except (TypeError, json.JSONDecodeError):
        checks = []
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("status") == "failed":
                check["agent_actionable"] = quality_gates.is_agent_actionable_failure(check)
    return {
        "id": run.id,
        "task_id": run.task_id,
        "review_id": run.review_id,
        "attempt": run.attempt,
        "commit_hash": run.commit_hash or "",
        "status": run.status,
        "summary": run.summary or "",
        "checks": checks if isinstance(checks, list) else [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/reviews/{review_id}/rerun-quality-gate")
def rerun_review_quality_gate(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-run checks on the unchanged review commit after platform remediation."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be checked again")
    task = db.get(Task, review.task_id)
    if not task or task.status != TaskStatus.REVIEWING or not task.worktree_path:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    latest = _latest_quality_gate(review.id, db)
    if latest and latest.status == "running":
        raise HTTPException(status_code=409, detail="Quality gate is already running")
    commit_hash = git.head_commit(task.worktree_path)
    if not commit_hash:
        raise HTTPException(status_code=409, detail="无法读取任务分支提交，不能重新检查")
    if not settings.QUALITY_GATE_ENABLED:
        # Gate disabled — synthesise a passed run so approval can proceed.
        attempt = db.query(QualityGateRun).filter(
            QualityGateRun.review_id == review.id
        ).count() + 1
        run = QualityGateRun(
            task_id=task.id,
            review_id=review.id,
            attempt=attempt,
            commit_hash=commit_hash,
            status="passed",
            results_json="[]",
            summary="确定性门禁已关闭，跳过全部检查",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return get_review_quality_gate(review_id, db, user)
    changed_files = sorted(git.changed_files_vs_base(task.worktree_path, commit_hash))
    run = quality_gates.execute_and_persist(
        db,
        task=task,
        review=review,
        workspace=task.worktree_path,
        commit_hash=commit_hash,
        changed_files=changed_files,
    )
    return get_review_quality_gate(review_id, db, user)


@router.post("/reviews/{review_id}/reviewers")
def configure_reviewers(
    review_id: int,
    body: ReviewersRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be configured")
    reviewer_ids = list(set(body.reviewer_ids))
    if body.required_approvals > len(reviewer_ids):
        raise HTTPException(status_code=400, detail="Required approvals cannot exceed reviewer count")
    member_ids = {row[0] for row in db.query(ProjectMember.user_id).filter(
        ProjectMember.project_id == review.project_id
    ).all()}
    if not set(reviewer_ids).issubset(member_ids):
        raise HTTPException(status_code=400, detail="All reviewers must be project members")
    if db.query(ReviewVote).filter(ReviewVote.review_id == review.id).first():
        raise HTTPException(status_code=409, detail="Reviewers cannot change after voting begins")
    round_ = _ensure_vote_round(review, db)
    round_.required_approvals = body.required_approvals
    round_.veto_on_reject = body.veto_on_reject
    db.query(ReviewReviewer).filter(ReviewReviewer.review_id == review.id).delete()
    db.add_all([ReviewReviewer(review_id=review.id, user_id=user_id) for user_id in reviewer_ids])
    db.commit()

    # Audit: 配置评审人 / 法定票数。
    audit_record(
        action=AuditAction.REVIEW_VOTE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=review.project_id,
        task_id=review.task_id,
        target_type="review",
        target_id=review.id,
        intent="配置评审人与法定批准票数",
        payload={
            "reviewer_ids": reviewer_ids,
            "required_approvals": body.required_approvals,
            "veto_on_reject": body.veto_on_reject,
        },
    )
    return _vote_summary(review, db)


@router.post("/reviews/{review_id}/vote")
def cast_review_vote(
    review_id: int,
    body: VoteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")
    if body.decision == "reject" and not body.comment.strip():
        raise HTTPException(status_code=400, detail="A rejection comment is required")
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_member(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Voting is closed")
    if body.decision == "approve":
        _require_passed_quality_gate(review, db)
    _ensure_vote_round(review, db)
    assignment = db.query(ReviewReviewer).filter(
        ReviewReviewer.review_id == review.id,
        ReviewReviewer.user_id == user.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="You are not assigned to this review")
    vote = db.query(ReviewVote).filter(
        ReviewVote.review_id == review.id,
        ReviewVote.user_id == user.id,
    ).first()
    if vote:
        vote.decision = body.decision
        vote.comment = body.comment.strip()
    else:
        db.add(ReviewVote(
            review_id=review.id,
            user_id=user.id,
            decision=body.decision,
            comment=body.comment.strip(),
        ))
    db.commit()

    # Audit: 成员投票（记录决策与意见作为意图）。
    audit_record(
        action=AuditAction.REVIEW_VOTE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=review.project_id,
        task_id=review.task_id,
        target_type="review",
        target_id=review.id,
        intent=body.comment.strip(),
        payload={"decision": body.decision},
    )

    summary = _vote_summary(review, db)
    round_ = _ensure_vote_round(review, db)
    queued_for_merge = False
    if body.decision == "reject" and round_.veto_on_reject:
        task = db.get(Task, review.task_id)
        if task and task.status == TaskStatus.REVIEWING:
            rejected_votes = db.query(ReviewVote).filter(
                ReviewVote.review_id == review.id,
                ReviewVote.decision == "reject",
            ).all()
            feedback = "\n\n".join(
                f"Reviewer #{vote.user_id}: {vote.comment}" for vote in rejected_votes
            )
            review.status = ReviewStatus.REJECTED
            review.human_feedback = feedback
            task.status = TaskStatus.RUNNING
            task.completed_at = None
            agent = db.get(Agent, task.agent_id)
            if agent:
                agent.status = AgentStatus.WORKING
            db.commit()
            if mem:
                try:
                    memory_doc = (
                        f"Review #{review.id} (task #{task.id}) was rejected. "
                        f"Apply this feedback on the retry: {feedback}"
                    )
                    metadata = {
                        "type": "review_decision",
                        "review_id": str(review.id),
                        "task_id": str(task.id),
                        "project_id": str(review.project_id),
                        "agent_id": str(task.agent_id),
                        "decision": "rejected",
                    }
                    mem.add_agent_memory(task.agent_id, memory_doc, metadata)
                    mem.add_project_memory(review.project_id, memory_doc, metadata)
                except Exception:
                    logger.exception("Failed to record review feedback in hierarchical memory")
            from app.services.execution_service import enqueue_agent_run
            enqueue_agent_run(task.id, feedback=feedback)
    elif (
        summary["reject_count"] == 0
        and summary["approve_count"] >= summary["required_approvals"]
    ):
        # Reaching the configured quorum is the approval action itself.  Do
        # not make a reviewer repeat it with a separate "confirm merge" click.
        task = db.get(Task, review.task_id)
        if task and task.status == TaskStatus.REVIEWING:
            _queue_review_merge(review, task, db)
            queued_for_merge = True
    from app.api.ws import broadcast_sync_to_project
    broadcast_sync_to_project(review.project_id, "review_vote_update", {
        "review_id": review.id,
        "project_id": review.project_id,
        **summary,
    })
    if review.status == ReviewStatus.REJECTED:
        broadcast_sync_to_project(review.project_id, "review_update", {
            "id": review.id,
            "task_id": review.task_id,
            "project_id": review.project_id,
            "status": "rejected",
        })
    return {**summary, "queued_for_merge": queued_for_merge}


@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    authorized_project = require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be approved")
    if not authorized_project.workspace_path:
        raise HTTPException(status_code=400, detail="Project workspace not initialized")

    # Update linked task status → approved
    task = db.get(Task, review.task_id)
    if not task or task.status != TaskStatus.REVIEWING:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    votes = _vote_summary(review, db)
    if votes["reject_count"]:
        raise HTTPException(status_code=409, detail="This review has rejection votes and cannot be approved")
    if votes["approve_count"] < votes["required_approvals"]:
        raise HTTPException(
            status_code=409,
            detail=f"Approval quorum not met ({votes['approve_count']}/{votes['required_approvals']})",
        )
    return _queue_review_merge(review, task, db)


@router.post("/reviews/{review_id}/reject")
def reject_review(
    review_id: int,
    body: RejectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject with feedback — agent will re-run to address the feedback."""
    feedback = body.feedback
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be rejected")

    if not feedback.strip():
        raise HTTPException(status_code=400, detail="Feedback is required for rejection")

    review.status = ReviewStatus.REJECTED
    review.human_feedback = feedback

    # Update task → running, agent → working for re-run
    task = db.get(Task, review.task_id)
    if not task or task.status != TaskStatus.REVIEWING:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    task.status = TaskStatus.RUNNING
    task.completed_at = None

    # Audit: 审查被驳回（记录反馈作为意图，将触发 Agent 重新执行）。
    audit_record(
        action=AuditAction.REVIEW_REJECT,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=review.project_id,
        task_id=review.task_id,
        target_type="review",
        target_id=review.id,
        intent=feedback,
        payload={"rerun": True},
    )

    # Set agent to WORKING to prevent concurrent task creation during the gap
    agent = db.get(Agent, task.agent_id) if task else None
    if agent:
        agent.status = AgentStatus.WORKING

    db.commit()

    # Broadcast state changes to all clients
    from app.api.ws import broadcast_sync
    broadcast_sync("review_update", {
        "id": review.id,
        "task_id": review.task_id,
        "project_id": review.project_id,
        "status": "rejected",
    })
    if task:
        broadcast_sync("task_update", {
            "id": task.id, "project_id": task.project_id, "status": "running",
        })
    if agent:
        broadcast_sync("agent_update", {
            "id": agent.id, "status": "working",
            "current_task_id": task.id if task else None,
        })

    # Preserve retry feedback in both the Agent and project layers.
    if mem:
        try:
            memory_doc = (
                f"Review #{review_id} (task #{review.task_id}) REJECTED. "
                f"Feedback to address: {feedback}"
            )
            metadata = {
                "type": "review_decision",
                "review_id": str(review_id),
                "task_id": str(review.task_id),
                "project_id": str(review.project_id),
                "agent_id": str(task.agent_id),
                "decision": "rejected",
            }
            mem.add_agent_memory(task.agent_id, memory_doc, metadata)
            mem.add_project_memory(review.project_id, memory_doc, metadata)
        except Exception:
            logger.exception("Failed to record review feedback in hierarchical memory")

    # Push system message
    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        msg.push(
            title="审查已驳回",
            body=f"审查 #{review_id}（任务 #{review.task_id}）已驳回，Agent 将根据反馈重新执行。",
            category=MessageCategory.REVIEW,
            level=MessageLevel.WARNING,
            project_id=review.project_id,
            link=f"/reviews?review_id={review_id}",
        )
    except Exception:
        pass

    # Trigger agent re-run with feedback via BackgroundTasks for safe shutdown
    # The pipeline will create the real Review with actual diff and summary
    from app.services.execution_service import enqueue_agent_run
    queued = enqueue_agent_run(task.id, feedback=feedback, queue_if_active=True)
    if not queued:
        task.status = TaskStatus.FAILED
        task.merge_error = "Agent 修改任务未能进入执行队列，请稍后手动重试"
        if agent:
            agent.status = AgentStatus.ERROR
        db.commit()
        raise HTTPException(status_code=503, detail=task.merge_error)

    return {"message": "Rejected — agent will re-run with feedback"}


@router.post("/reviews/{review_id}/reject-quality-gate")
def reject_failed_quality_gate(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a failed deterministic gate to the Agent with exact findings."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be rejected")
    run = _latest_quality_gate(review.id, db)
    if not run or run.status != "failed":
        raise HTTPException(status_code=409, detail="The latest quality gate is not failed")
    try:
        checks = json.loads(run.results_json or "[]")
    except (TypeError, json.JSONDecodeError):
        checks = []
    failed = [
        check for check in checks
        if isinstance(check, dict) and check.get("status") == "failed"
    ]
    platform_failed = [
        check for check in failed
        if not quality_gates.is_agent_actionable_failure(check)
    ]
    if platform_failed:
        labels = "、".join(
            str(check.get("label") or check.get("key") or "未知检查项")
            for check in platform_failed
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"以下失败属于门禁执行环境问题，Agent 修改代码无法解决：{labels}。"
                "请平台管理员先安装检查工具或修正 backend/.env 中的门禁命令"
            ),
        )
    details = "\n\n".join(
        f"【{check.get('label') or check.get('key') or '检查项'}】\n"
        f"复现命令：{check.get('command') or '内置扫描'}\n"
        f"{str(check.get('output') or '未提供失败详情')[:2000]}"
        for check in failed
    )
    feedback = (
        "确定性合并门禁未通过。你正在处理修订任务，必须直接修改工作区文件，"
        "不能只解释原因或输出建议。请逐项修复、补充测试，并在结束前检查 Git diff "
        "确认本轮产生了针对失败项的实际代码变更：\n\n"
        f"{details or run.summary or '门禁执行失败，请检查项目测试和安全配置。'}"
    )
    return reject_review(
        review_id,
        RejectRequest(feedback=feedback),
        BackgroundTasks(),
        db,
        user,
    )


@router.post("/reviews/{review_id}/close")
def close_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Close the review without merging — terminal rejection, no re-run."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    require_project_admin(review.project_id, user, db)
    if review.status != ReviewStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reviews can be closed")

    review.status = ReviewStatus.REJECTED

    # Update linked task status → rejected (terminal)
    task = db.get(Task, review.task_id)
    if not task or task.status != TaskStatus.REVIEWING:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    task.status = TaskStatus.REJECTED

    # Release the agent so it can accept new work.
    agent = db.get(Agent, task.agent_id)
    if agent and agent.status == AgentStatus.DONE:
        agent.status = AgentStatus.IDLE

    db.commit()

    # Audit: 审查被关闭（终止驳回，未合并）。
    audit_record(
        action=AuditAction.REVIEW_CLOSE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=review.project_id,
        task_id=review.task_id,
        target_type="review",
        target_id=review.id,
        intent="关闭审查（终止，未合并）",
    )

    # ── WebSocket broadcasts ──────────────────────────────────────
    broadcast_sync("review_update", {
        "id": review.id, "task_id": review.task_id,
        "project_id": review.project_id, "status": "rejected",
    })
    broadcast_sync("task_update", {
        "id": task.id, "project_id": task.project_id, "status": "rejected",
    })
    if agent:
        broadcast_sync("agent_update", {"id": agent.id, "status": "idle"})

    # Clean up task worktree and branch
    from app.models.models import Project
    proj = db.get(Project, review.project_id)
    if proj and proj.workspace_path and task.worktree_path:
        branch_name = task.branch_name or f"task/{review.task_id}"
        git.switch_branch(proj.workspace_path, "master")
        git.cleanup_task_resources(proj.workspace_path, task.worktree_path, branch_name)

    # Record the terminal outcome in the Agent and project layers.
    if mem:
        try:
            memory_doc = f"Review #{review_id} (task #{review.task_id}) CLOSED (terminal rejection)."
            metadata = {
                "type": "review_decision",
                "review_id": str(review_id),
                "task_id": str(review.task_id),
                "project_id": str(review.project_id),
                "agent_id": str(task.agent_id),
                "decision": "closed",
            }
            mem.add_agent_memory(task.agent_id, memory_doc, metadata)
            mem.add_project_memory(review.project_id, memory_doc, metadata)
        except Exception:
            logger.exception("Failed to record terminal review outcome in hierarchical memory")

    # Push system message
    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        msg.push(
            title="审查已关闭",
            body=f"审查 #{review_id}（任务 #{review.task_id}）已关闭，任务终止，未合并。",
            category=MessageCategory.REVIEW,
            level=MessageLevel.INFO,
            project_id=review.project_id,
            link=f"/reviews?review_id={review_id}",
        )
    except Exception:
        pass

    return {"message": "Closed"}
