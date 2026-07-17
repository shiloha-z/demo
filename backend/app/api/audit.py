"""Audit trail API.

Exposes the append-only ledger for the accountability UI:
  - list with filters (project / actor / action / time range / target)
  - a "responsibility chain" view that replays every event tied to a task
    (or task node) so any incident can be traced back to who initiated,
    who approved, what instruction the AI ran, and what changed.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_project_member
from app.models.models import (
    User,
    Project,
    AuditLog,
    AuditAction,
    AuditActorType,
    Task,
    ProjectMember,
)
from app.services.audit_actions import ACTION_REGISTRY, ACTION_GROUPS

router = APIRouter(prefix="/api/audit", tags=["Audit"])


def _to_dict(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "actor_id": log.actor_id,
        "actor_type": log.actor_type.value if hasattr(log.actor_type, "value") else log.actor_type,
        "actor_name": log.actor.display_name or log.actor.username if log.actor else "",
        "project_id": log.project_id,
        "task_id": log.task_id,
        "task_node_id": log.task_node_id,
        "action": log.action.value if hasattr(log.action, "value") else log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "intent": log.intent,
        "payload": log.payload,
        "impact": log.impact,
        "ip": log.ip,
        "ua": log.ua,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("")
def list_audit(
    project_id: int | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    from_time: str | None = Query(default=None, description="ISO 起始时间"),
    to_time: str | None = Query(default=None, description="ISO 结束时间"),
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List audit entries with optional filters.

    Project members only see entries for projects they belong to; without a
    project filter, only projects the user is a member of are returned.
    """
    q = db.query(AuditLog)

    if project_id is not None:
        require_project_member(project_id, user, db)
        q = q.filter(AuditLog.project_id == project_id)
    else:
        # No project filter: only show entries for projects the user can see.
        member_project_ids = {row[0] for row in db.query(Project.id).outerjoin(
            ProjectMember, Project.id == ProjectMember.project_id,
        ).filter(
            (Project.owner_id == user.id) | (ProjectMember.user_id == user.id)
        ).all()}
        q = q.filter(AuditLog.project_id.in_(member_project_ids))

    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)
    if action:
        q = q.filter(AuditLog.action == action)
    if task_id is not None:
        q = q.filter(AuditLog.task_id == task_id)
    if from_time:
        try:
            q = q.filter(AuditLog.created_at >= datetime.fromisoformat(from_time))
        except ValueError:
            pass
    if to_time:
        try:
            q = q.filter(AuditLog.created_at <= datetime.fromisoformat(to_time))
        except ValueError:
            pass

    q = q.order_by(desc(AuditLog.created_at)).limit(limit)
    return {"entries": [_to_dict(log) for log in q.all()]}


@router.get("/chain")
def responsibility_chain(
    task_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Replay the full accountability chain for one task.

    Returns the linked project and the ordered list of every audit event tied
    to that task (who initiated → who approved → what instruction the AI ran →
    what changed). New event types are rendered automatically from the action
    registry served by GET /api/audit/actions.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_member(task.project_id, user, db)

    entries = (
        db.query(AuditLog)
        .filter(AuditLog.task_id == task_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    return {
        "task_id": task_id,
        "project_id": task.project_id,
        "timeline": [_to_dict(log) for log in entries],
    }


@router.get("/actions")
def audit_action_options(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the enum values + registry metadata so the UI can render filter
    chips and badges without hard-coding labels/colors.

    `actions` carries each action's label, group, and color token; adding a new
    audit action only requires editing the registry (see audit_actions.py),
    no frontend change needed.
    """
    actions = [
        {
            "value": value,
            "label": meta["label"],
            "group": meta["group"],
            "group_label": ACTION_GROUPS.get(meta["group"], {}).get("label", meta["group"]),
            "token": ACTION_GROUPS.get(meta["group"], {}).get("token", "system"),
        }
        for value, meta in ACTION_REGISTRY.items()
    ]
    return {
        "actions": actions,
        "actor_types": [t.value for t in AuditActorType],
    }
