"""Shared project-level authorization helpers."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import Project, ProjectMember, ProjectRole, User


def require_project_member(project_id: int, user: User, db: Session) -> Project:
    """Return a project only when the caller is one of its members."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.owner_id == user.id:
        return project

    membership = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project membership required")
    return project


def require_project_admin(project_id: int, user: User, db: Session) -> Project:
    """Return a project only for its owner or an administrator."""
    project = require_project_member(project_id, user, db)
    if project.owner_id == user.id:
        return project

    membership = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ).first()
    if not membership or membership.role != ProjectRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project administrator permission required")
    return project
