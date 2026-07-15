from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Review, ReviewStatus, Task, TaskStatus, Version
from app.services import git_service as git

# Lazy import — memory_service may fail if chromadb not installed
try:
    from app.services import memory_service as mem
except ImportError:
    mem = None

router = APIRouter(prefix="/api", tags=["Reviews"])


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


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    reviews = db.query(Review).filter(Review.project_id == project_id).order_by(Review.id.desc()).all()
    return [ReviewResponse.model_validate(r) for r in reviews]


@router.get("/reviews/{review_id}", response_model=ReviewResponse)
def get_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return ReviewResponse.model_validate(review)


@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.status = ReviewStatus.APPROVED

    # Update linked task status → approved
    task = db.query(Task).get(review.task_id)
    if task:
        task.status = TaskStatus.APPROVED

    db.commit()

    # Merge task branch → master, then commit
    from app.models.models import Project
    proj = db.query(Project).get(review.project_id)
    if proj and proj.workspace_path:
        branch_name = f"task/{review.task_id}"
        # 1. Merge task branch into master (agent already committed on the branch)
        merged = git.merge_branch(proj.workspace_path, branch_name)
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

    # Record to project memory
    if mem:
        try:
            mem.add_project_memory(review.project_id,
                f"Review #{review_id} (task #{review.task_id}) APPROVED. "
                f"Changes merged to master.",
                {"type": "review_decision", "review_id": str(review_id), "decision": "approved"})
        except Exception:
            pass

    return {"message": "Approved"}


@router.post("/reviews/{review_id}/reject")
def reject_review(
    review_id: int,
    body: RejectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject with feedback — agent will re-run to address the feedback."""
    feedback = body.feedback
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if not feedback.strip():
        raise HTTPException(status_code=400, detail="Feedback is required for rejection")

    review.status = ReviewStatus.REJECTED
    review.human_feedback = feedback

    # Update task → running so agent can re-run
    task = db.query(Task).get(review.task_id)
    if task:
        task.status = TaskStatus.RUNNING

    # Create a new pending review for the next round
    new_review = Review(
        task_id=review.task_id,
        project_id=review.project_id,
        diff_content="",
        agent_review_summary="",
        status=ReviewStatus.PENDING,
    )
    db.add(new_review)
    db.commit()
    db.refresh(new_review)

    # Record to project memory
    try:
        mem.add_project_memory(review.project_id,
            f"Review #{review_id} (task #{review.task_id}) REJECTED. Feedback: {feedback}",
            {"type": "review_decision", "review_id": str(review_id), "decision": "rejected",
             "new_review_id": str(new_review.id)})
    except Exception:
        pass

    # Trigger agent re-run with feedback
    from app.services.agent_runner import run_agent_pipeline
    from fastapi import BackgroundTasks
    # Fire-and-forget: the reject endpoint doesn't have BackgroundTasks injected,
    # so we launch in a thread via the agent_runner's existing mechanism
    import threading
    t = threading.Thread(target=run_agent_pipeline, args=(task.id, feedback), daemon=True)
    t.start()

    return {"message": "Rejected — agent will re-run with feedback", "new_review_id": new_review.id}


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

    review.status = ReviewStatus.REJECTED

    # Update linked task status → rejected (terminal)
    task = db.query(Task).get(review.task_id)
    if task:
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
