from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_project_admin, require_project_member
from app.models.models import User, Review, ReviewStatus, ReviewRound, ReviewReviewer, ReviewVote, ProjectMember, Task, TaskStatus, Version, Agent, AgentStatus
from app.services import git_service as git

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


def _queue_review_merge(review: Review, task: Task, db: Session) -> dict:
    """Persist approval first, then let the project merge worker serialize it."""
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
    return {"message": "Approved and queued for merge"}


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_project_member(project_id, user, db)
    reviews = db.query(Review).filter(Review.project_id == project_id).order_by(Review.id.desc()).all()
    return [ReviewResponse.model_validate(r) for r in reviews]


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
    summary = _vote_summary(review, db)
    round_ = _ensure_vote_round(review, db)
    queued_for_merge = False
    if body.decision == "reject" and round_.veto_on_reject:
        task = db.query(Task).get(review.task_id)
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
            agent = db.query(Agent).get(task.agent_id)
            if agent:
                agent.status = AgentStatus.WORKING
            db.commit()
            from app.services.execution_service import enqueue_agent_run
            enqueue_agent_run(task.id, feedback=feedback)
    elif (
        summary["reject_count"] == 0
        and summary["approve_count"] >= summary["required_approvals"]
    ):
        # Reaching the configured quorum is the approval action itself.  Do
        # not make a reviewer repeat it with a separate "confirm merge" click.
        task = db.query(Task).get(review.task_id)
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
    task = db.query(Task).get(review.task_id)
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

    # Merge task branch → master, then commit
    from app.models.models import Project
    proj = db.query(Project).get(review.project_id)
    if proj and proj.workspace_path:
        branch_name = f"task/{review.task_id}"
        # 1. Merge task branch into master (agent already committed on the branch)
        merged = git.merge_branch(proj.workspace_path, branch_name)
        if not merged:
            raise HTTPException(status_code=409, detail="Could not merge task branch")
        if merged:
            # A fast-forward merge leaves no uncommitted changes, so the
            # normal `commit()` returns None. Fall back to an empty auditable
            # commit so a Version record is always created for the approval.
            commit_hash = git.commit(
                proj.workspace_path, f"Review #{review_id} approved (task #{review.task_id})"
            ) or git.commit_allow_empty(
                proj.workspace_path, f"Review #{review_id} approved (task #{review.task_id})"
            )
            if commit_hash:
                v = Version(project_id=review.project_id, commit_hash=commit_hash,
                            commit_message=f"Review #{review_id} approved", review_id=review.id)
                db.add(v)
                db.commit()
        # 2. Clean up the task branch
        git.delete_branch(proj.workspace_path, branch_name)

    review.status = ReviewStatus.APPROVED
    task.status = TaskStatus.APPROVED
    db.commit()

    from app.api.ws import broadcast_sync
    broadcast_sync("review_update", {
        "id": review.id, "task_id": review.task_id,
        "project_id": review.project_id, "status": "approved",
    })
    broadcast_sync("task_update", {
        "id": task.id, "project_id": task.project_id, "status": "approved",
    })
    broadcast_sync("version_update", {"project_id": review.project_id})
    broadcast_sync("file_change", {"project_id": review.project_id})

    # Record to project memory
    if mem:
        try:
            mem.add_project_memory(review.project_id,
                f"Review #{review_id} (task #{review.task_id}) APPROVED. "
                f"Changes merged to master.",
                {"type": "review_decision", "review_id": str(review_id), "decision": "approved"})
        except Exception:
            pass

    # Push system message
    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        msg.push(
            title="审查已通过",
            body=f"审查 #{review_id}（任务 #{review.task_id}）已通过，变更已合并到主分支。",
            category=MessageCategory.REVIEW,
            level=MessageLevel.SUCCESS,
            project_id=review.project_id,
            link=f"/versions",
        )
    except Exception:
        pass

    return {"message": "Approved"}


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
    task = db.query(Task).get(review.task_id)
    if not task or task.status != TaskStatus.REVIEWING:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    task.status = TaskStatus.RUNNING
    task.completed_at = None

    # Set agent to WORKING to prevent concurrent task creation during the gap
    agent = db.query(Agent).get(task.agent_id) if task else None
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

    # Record to project memory
    try:
        mem.add_project_memory(review.project_id,
            f"Review #{review_id} (task #{review.task_id}) REJECTED. Feedback: {feedback}",
            {"type": "review_decision", "review_id": str(review_id), "decision": "rejected"})
    except Exception:
        pass

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
    enqueue_agent_run(task.id, feedback=feedback)

    return {"message": "Rejected — agent will re-run with feedback"}


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
    task = db.query(Task).get(review.task_id)
    if not task or task.status != TaskStatus.REVIEWING:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    task.status = TaskStatus.REJECTED

    db.commit()

    # Switch back to master and delete the task branch
    from app.models.models import Project
    proj = db.query(Project).get(review.project_id)
    if proj and proj.workspace_path:
        branch_name = f"task/{review.task_id}"
        git.switch_branch(proj.workspace_path, "master")
        git.delete_branch(proj.workspace_path, branch_name)

    # Record to project memory
    if mem:
        try:
            mem.add_project_memory(review.project_id,
                f"Review #{review_id} (task #{review.task_id}) CLOSED (terminal rejection).",
                {"type": "review_decision", "review_id": str(review_id), "decision": "closed"})
        except Exception:
            pass

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


@router.get("/reviews/pending-count")
def pending_review_count(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return count of pending reviews, optionally scoped to a project."""
    q = db.query(Review).filter(Review.status == ReviewStatus.PENDING)
    if project_id is not None:
        q = q.filter(Review.project_id == project_id)
    return {"count": q.count()}
