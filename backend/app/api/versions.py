"""Version history API — list commits and rollback."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Project, Version
from app.services import git_service as git

router = APIRouter(prefix="/api/projects/{project_id}/versions", tags=["Versions"])


# ── Schemas ───────────────────────────────────────────────────────────

class VersionResponse(BaseModel):
    id: int
    commit_hash: str
    short_hash: str
    commit_message: str
    review_id: int | None
    created_at: str | None

    class Config:
        from_attributes = True


class RollbackResponse(BaseModel):
    success: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────────────

def _version_to_response(v: Version) -> VersionResponse:
    return VersionResponse(
        id=v.id,
        commit_hash=v.commit_hash,
        short_hash=v.commit_hash[:7] if v.commit_hash else "",
        commit_message=v.commit_message,
        review_id=v.review_id,
        created_at=v.created_at.isoformat() if v.created_at else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[VersionResponse])
def list_versions(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all versions (commits) for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    versions = (
        db.query(Version)
        .filter(Version.project_id == project_id)
        .order_by(Version.created_at.desc())
        .all()
    )
    return [_version_to_response(v) for v in versions]


@router.post("/{version_id}/rollback", response_model=RollbackResponse)
def rollback_version(
    project_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rollback project to a specific version."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.workspace_path:
        raise HTTPException(status_code=400, detail="Project has no workspace")

    target = db.query(Version).filter(Version.id == version_id, Version.project_id == project_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Version not found")

    new_hash = git.rollback(
        project.workspace_path,
        target.commit_hash,
        message=f"Revert to {target.commit_hash[:7]}",
    )
    if not new_hash:
        raise HTTPException(status_code=500, detail="Git rollback failed")

    # Record this rollback as a new auditable version entry — but only when a
    # real new commit was created (skip no-op rollbacks to the current version).
    if new_hash != target.commit_hash:
        rollback_version = Version(
            project_id=project_id,
            commit_hash=new_hash,
            commit_message=f"Revert to {target.commit_hash[:7]}",
            review_id=target.review_id,
        )
        db.add(rollback_version)
        db.commit()

    # Notify the frontend to refresh the file tree.
    try:
        from app.api.ws import broadcast_sync
        broadcast_sync("file_change", {"project_id": project_id})
    except Exception:
        pass

    return RollbackResponse(
        success=True,
        message=f"已回退到版本 {target.commit_hash[:7]}",
    )
