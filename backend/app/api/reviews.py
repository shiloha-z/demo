from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Review, ReviewStatus, Version
from app.services import git_service as git

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
    db.commit()

    # Merge task branch → master, then commit
    from app.models.models import Project
    proj = db.query(Project).get(review.project_id)
    if proj and proj.workspace_path:
        branch_name = f"task/{review.task_id}"
        # 1. Merge task branch into master (agent already committed on the branch)
        merged = git.merge_branch(proj.workspace_path, branch_name)
        if merged:
            commit_hash = git.commit(proj.workspace_path, f"Review #{review_id} approved (task #{review.task_id})")
            if commit_hash:
                v = Version(project_id=review.project_id, commit_hash=commit_hash,
                            commit_message=f"Review #{review_id} approved", review_id=review.id)
                db.add(v)
                db.commit()
        # 2. Clean up the task branch
        git.delete_branch(proj.workspace_path, branch_name)

    return {"message": "Approved"}


@router.post("/reviews/{review_id}/reject")
def reject_review(
    review_id: int,
    feedback: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.status = ReviewStatus.REJECTED
    review.human_feedback = feedback
    db.commit()

    # Switch back to master and delete the task branch
    from app.models.models import Project
    proj = db.query(Project).get(review.project_id)
    if proj and proj.workspace_path:
        branch_name = f"task/{review.task_id}"
        git.switch_branch(proj.workspace_path, "master")
        git.delete_branch(proj.workspace_path, branch_name)

    return {"message": "Rejected"}


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
