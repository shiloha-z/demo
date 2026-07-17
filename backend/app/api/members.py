"""Project member management API + permission dependencies.

Roles (from highest to lowest):
  - owner:  full control, can transfer ownership
  - admin:  manage members (except owner), manage tasks/reviews
  - member: view, create tasks, chat
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.auth import get_current_user
from datetime import datetime, timezone
from app.models.models import User, Project, ProjectMember, ProjectRole, JoinRequest, JoinStatus, Review, ReviewVote, ReviewReviewer
from app.services.audit_service import record as audit_record
from app.models.models import AuditAction, AuditActorType

router = APIRouter(prefix="/api", tags=["Members"])
# Kept only so old function bodies remain available for migration reference.
# It is intentionally not registered by the application: join requests are
# served exclusively by the canonical project-ID routes in projects.py.
legacy_router = APIRouter(prefix="/api", tags=["Legacy Members"])


def _broadcast_member_update(project_id: int) -> None:
    from app.api.ws import broadcast_sync
    payload = {"project_id": project_id}
    broadcast_sync("member_update", payload)
    broadcast_sync("project_update", {"action": "members_changed", **payload})


# ── Schemas ───────────────────────────────────────────────────────────

class MemberResponse(BaseModel):
    id: int
    project_id: int
    user_id: int
    username: str
    display_name: str
    role: str
    joined_at: Optional[str] = None

    class Config:
        from_attributes = True


class AddMemberRequest(BaseModel):
    username: str
    role: str = "member"


class UpdateRoleRequest(BaseModel):
    role: str


class TransferRequest(BaseModel):
    new_owner_username: str


# ── Permission helpers ────────────────────────────────────────────────

def get_member(project_id: int, user_id: int, db: Session) -> ProjectMember | None:
    """Get user's membership in a project. Returns None if not a member."""
    return db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
    ).first()


def require_member(project_id: int, user: User, db: Session) -> ProjectMember:
    """Require that the user is a member of the project. Owner is always allowed."""
    member = get_member(project_id, user.id, db)
    if member:
        return member
    # Owner is always considered a member, even if no ProjectMember record
    project = db.query(Project).filter(Project.id == project_id).first()
    if project and project.owner_id == user.id:
        # Return a synthetic member for owner
        return ProjectMember(
            project_id=project_id,
            user_id=user.id,
            role=ProjectRole.OWNER,
            joined_at=project.created_at,
        )
    raise HTTPException(status_code=403, detail="You are not a member of this project")


def require_role(project_id: int, user: User, db: Session, *roles: str) -> ProjectMember:
    """Require that the user has one of the given roles. Raises 403 if not."""
    member = require_member(project_id, user, db)
    if member.role.value not in roles:
        role_names = {"owner": "项目主管", "admin": "管理员", "member": "一般成员"}
        allowed = "/".join(role_names.get(r, r) for r in roles)
        raise HTTPException(
            status_code=403,
            detail=f"This action requires {allowed} permission"
        )
    return member


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/members", response_model=list[MemberResponse])
def list_members(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all members of a project (must be a member to view)."""
    require_member(project_id, user, db)

    members = (
        db.query(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .filter(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.role.desc(), ProjectMember.joined_at.asc())
        .all()
    )
    return [
        MemberResponse(
            id=pm.id,
            project_id=pm.project_id,
            user_id=pm.user_id,
            username=u.username,
            display_name=u.display_name or u.username,
            role=pm.role.value,
            joined_at=pm.joined_at.isoformat() if pm.joined_at else None,
        )
        for pm, u in members
    ]


@router.post("/projects/{project_id}/members")
def add_member(
    project_id: int,
    body: AddMemberRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a new member to the project. Requires owner or admin."""
    require_role(project_id, user, db, "owner", "admin")

    if body.role not in ("owner", "admin", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")

    if body.role == "owner":
        raise HTTPException(status_code=400, detail="Use ownership transfer to assign the project owner")

    target = db.query(User).filter(User.username == body.username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already a member
    existing = get_member(project_id, target.id, db)
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    pm = ProjectMember(
        project_id=project_id,
        user_id=target.id,
        role=ProjectRole(body.role),
    )
    db.add(pm)
    db.commit()
    db.refresh(pm)

    # Audit: 新增成员。
    audit_record(
        action=AuditAction.MEMBER_ADD,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="member",
        target_id=target.id,
        intent=f"添加成员 {target.username}（角色：{body.role}）",
    )

    _broadcast_member_update(project_id)

    return {
        "message": f"Added {target.username} as {body.role}",
        "member": {
            "id": pm.id,
            "user_id": pm.user_id,
            "username": target.username,
            "display_name": target.display_name or target.username,
            "role": pm.role.value,
        }
    }


@router.put("/projects/{project_id}/members/{member_user_id}")
def update_member_role(
    project_id: int,
    member_user_id: int,
    body: UpdateRoleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change a member's role. Requires owner or admin. Only owner can set owner role."""
    member = require_role(project_id, user, db, "owner", "admin")

    if body.role not in ("owner", "admin", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")

    if body.role == "owner":
        raise HTTPException(status_code=400, detail="Use ownership transfer to assign the project owner")

    # Cannot change owner's role (use transfer instead)
    target_pm = get_member(project_id, member_user_id, db)
    if not target_pm:
        raise HTTPException(status_code=404, detail="Member not found")
    if target_pm.role == ProjectRole.OWNER and body.role != "owner":
        raise HTTPException(
            status_code=400,
            detail="Cannot change owner role — use transfer ownership instead"
        )

    target_pm.role = ProjectRole(body.role)
    db.commit()

    # Audit: 调整成员角色。
    audit_record(
        action=AuditAction.MEMBER_ADD,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="member",
        target_id=member_user_id,
        intent=f"调整成员角色为 {body.role}",
    )

    _broadcast_member_update(project_id)

    return {"message": f"Role updated to {body.role}"}


@router.delete("/projects/{project_id}/members/{member_user_id}")
def remove_member(
    project_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a member from the project. Owner/admin can remove members, users can leave."""
    # Owner cannot be removed
    target_pm = get_member(project_id, member_user_id, db)
    if not target_pm:
        raise HTTPException(status_code=404, detail="Member not found")

    if target_pm.role == ProjectRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot remove project owner")

    # Clean up stale reviewer/voter assignments for this member in this project
    def _cleanup_member_review_data(uid: int, pid: int):
        review_ids = [
            row[0] for row in
            db.query(Review.id).filter(Review.project_id == pid).all()
        ]
        if review_ids:
            db.query(ReviewVote).filter(
                ReviewVote.review_id.in_(review_ids),
                ReviewVote.user_id == uid,
            ).delete(synchronize_session=False)
            db.query(ReviewReviewer).filter(
                ReviewReviewer.review_id.in_(review_ids),
                ReviewReviewer.user_id == uid,
            ).delete(synchronize_session=False)

    # Self-leave: any member can leave
    if member_user_id == user.id:
        _cleanup_member_review_data(member_user_id, project_id)
        db.delete(target_pm)
        db.commit()

        # Audit: 成员主动退出。
        audit_record(
            action=AuditAction.MEMBER_REMOVE,
            actor_id=user.id,
            actor_type=AuditActorType.HUMAN,
            project_id=project_id,
            target_type="member",
            target_id=member_user_id,
            intent="成员主动退出项目",
        )

        _broadcast_member_update(project_id)
        return {"message": "You have left the project"}

    # Removing others: requires owner or admin
    require_role(project_id, user, db, "owner", "admin")

    # Admin cannot remove another admin/owner
    acting = get_member(project_id, user.id, db)
    if acting and acting.role == ProjectRole.ADMIN:
        if target_pm.role in (ProjectRole.OWNER, ProjectRole.ADMIN):
            raise HTTPException(status_code=403, detail="Admins cannot remove other admins or owners")

    _cleanup_member_review_data(member_user_id, project_id)
    db.delete(target_pm)
    db.commit()

    # Audit: 移除成员。
    audit_record(
        action=AuditAction.MEMBER_REMOVE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="member",
        target_id=member_user_id,
        intent=f"移除成员（{target_pm.role.value}）",
    )

    _broadcast_member_update(project_id)

    return {"message": "Member removed"}


@router.post("/projects/{project_id}/transfer")
def transfer_ownership(
    project_id: int,
    body: TransferRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Transfer project ownership to another member. Only the current owner can do this."""
    owner_pm = require_role(project_id, user, db, "owner")

    # Prevent accidentally transferring to self
    target_user = db.query(User).filter(User.username == body.new_owner_username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    if target_user.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot transfer ownership to yourself")

    target_pm = get_member(project_id, target_user.id, db)
    if not target_pm:
        raise HTTPException(status_code=404, detail="Target user is not a member of this project")

    # Ensure there is exactly one owner before transfer (safety check)
    owner_count = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.role == ProjectRole.OWNER,
    ).count()
    if owner_count > 1:
        # Clean up duplicate owners — keep only the current user as owner
        db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.role == ProjectRole.OWNER,
            ProjectMember.user_id != user.id,
        ).update({ProjectMember.role: ProjectRole.MEMBER}, synchronize_session=False)

    # Demote current owner, promote target
    owner_pm.role = ProjectRole.MEMBER

    # Demote any other legacy duplicate owners
    db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.role == ProjectRole.OWNER,
        ProjectMember.user_id != target_user.id,
    ).update({ProjectMember.role: ProjectRole.MEMBER}, synchronize_session=False)
    target_pm.role = ProjectRole.OWNER

    # Update project owner_id shortcut
    project = db.get(Project, project_id)
    old_owner_name = ""
    if project:
        old_owner_name = project.owner_name
        project.owner_id = target_user.id

    db.commit()

    # Audit: 转让项目所有权（安全敏感操作）。
    audit_record(
        action=AuditAction.TRANSFER_OWNER,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        intent=f"项目主管由 {old_owner_name} 变更为 {target_user.username}",
    )

    _broadcast_member_update(project_id)

    # Push system message about ownership change
    try:
        from app.services import message_service as msg
        from app.models.models import MessageCategory, MessageLevel
        msg.push(
            title="项目主管已变更",
            body=f"项目主管已由 {old_owner_name} 变更为 {target_user.username}",
            category=MessageCategory.MEMBER,
            level=MessageLevel.WARNING,
            project_id=project_id,
        )
    except Exception:
        pass

    return {"message": f"Ownership transferred to {target_user.username}"}


# ── Join Requests ────────────────────────────────────────────────────

class JoinRequestResponse(BaseModel):
    id: int
    project_id: int
    user_id: int
    username: str
    status: str
    created_at: str | None = None
    reviewed_at: str | None = None
    project_name: str = ""


@legacy_router.get("/projects/{project_id}/join-requests", response_model=list[JoinRequestResponse])
def list_join_requests(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List join requests for a project. Owner/admin only."""
    require_role(project_id, user, db, "owner", "admin")

    project = db.get(Project, project_id)
    requests = (
        db.query(JoinRequest)
        .filter(JoinRequest.project_id == project_id)
        .order_by(JoinRequest.status == "pending", JoinRequest.created_at.desc())
        .all()
    )
    return [
        JoinRequestResponse(
            id=r.id, project_id=r.project_id, user_id=r.user_id,
            username=r.username, status=r.status.value,
            created_at=r.created_at.isoformat() if r.created_at else None,
            reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
            project_name=project.name if project else "",
        )
        for r in requests
    ]


@legacy_router.get("/projects/{project_id}/my-request")
def get_my_request(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get the current user's join request for a project (if any)."""
    req = (
        db.query(JoinRequest)
        .filter(
            JoinRequest.project_id == project_id,
            JoinRequest.user_id == user.id,
        )
        .order_by(JoinRequest.created_at.desc())
        .first()
    )
    if not req:
        return {"request": None}
    return {"request": JoinRequestResponse(
        id=req.id, project_id=req.project_id, user_id=req.user_id,
        username=req.username, status=req.status.value,
        created_at=req.created_at.isoformat() if req.created_at else None,
        reviewed_at=req.reviewed_at.isoformat() if req.reviewed_at else None,
    )}


@legacy_router.post("/projects/{project_id}/join")
def request_join(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit a request to join a project."""
    # Check already a member
    existing = get_member(project_id, user.id, db)
    if existing:
        raise HTTPException(status_code=409, detail="You are already a member of this project")

    # Check if already has a pending request
    pending = (
        db.query(JoinRequest)
        .filter(
            JoinRequest.project_id == project_id,
            JoinRequest.user_id == user.id,
            JoinRequest.status == JoinStatus.PENDING,
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=409, detail="You already have a pending join request")

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    req = JoinRequest(
        project_id=project_id,
        user_id=user.id,
        username=user.username,
        status=JoinStatus.PENDING,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return {"message": "Join request submitted", "id": req.id, "status": "pending"}


@legacy_router.post("/projects/{project_id}/join-requests/{request_id}/approve")
def approve_join(
    project_id: int,
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve a join request. Owner/admin only."""
    require_role(project_id, user, db, "owner", "admin")

    req = db.query(JoinRequest).filter(
        JoinRequest.id == request_id,
        JoinRequest.project_id == project_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != JoinStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request already processed")

    req.status = JoinStatus.APPROVED
    req.reviewed_at = datetime.now(timezone.utc)

    # Add as member
    existing = get_member(project_id, req.user_id, db)
    if not existing:
        db.add(ProjectMember(
            project_id=project_id,
            user_id=req.user_id,
            role=ProjectRole.MEMBER,
        ))

    db.commit()

    # Audit: 批准加入申请。
    audit_record(
        action=AuditAction.JOIN_APPROVE,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="join_request",
        target_id=request_id,
        intent=f"批准 {req.username} 的加入申请",
    )

    _broadcast_member_update(project_id)

    return {"message": f"Request approved — {req.username} is now a member"}


@legacy_router.post("/projects/{project_id}/join-requests/{request_id}/reject")
def reject_join(
    project_id: int,
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject a join request. Owner/admin only."""
    require_role(project_id, user, db, "owner", "admin")

    req = db.query(JoinRequest).filter(
        JoinRequest.id == request_id,
        JoinRequest.project_id == project_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != JoinStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request already processed")

    req.status = JoinStatus.REJECTED
    req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    # Audit: 驳回加入申请。
    audit_record(
        action=AuditAction.JOIN_REJECT,
        actor_id=user.id,
        actor_type=AuditActorType.HUMAN,
        project_id=project_id,
        target_type="join_request",
        target_id=request_id,
        intent=f"驳回 {req.username} 的加入申请",
    )

    return {"message": f"Request rejected for {req.username}"}
