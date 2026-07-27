"""Message center service.

Thin helper around the `Message` table. Designed to be inserted into existing
business flows (agent_runner, reviews, versions) without altering their logic.

`push` optionally broadcasts a `message_new` WebSocket event so the frontend
can refresh its unread badge in real time — reusing the existing broadcast_sync,
no new protocol.
"""

from datetime import datetime, timezone
from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from app.models.models import (
    Message,
    MessageRead,
    MessageCategory,
    MessageLevel,
    ProjectMember,
)
from app.core.database import SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def push(
    *,
    title: str,
    body: str = "",
    category: MessageCategory = MessageCategory.SYSTEM,
    level: MessageLevel = MessageLevel.INFO,
    project_id: int | None = None,
    recipient_id: int | None = None,
    link: str = "",
) -> Message:
    """Create a message row in its own short-lived session (safe to call from
    background threads / non-request contexts).
    """
    msg = Message(
        title=title,
        body=body,
        category=category,
        level=level,
        project_id=project_id,
        recipient_id=recipient_id,
        link=link,
        created_at=_now(),
    )
    db = SessionLocal()
    try:
        db.add(msg)
        db.commit()
        db.refresh(msg)
        _broadcast(msg)
        return msg
    finally:
        db.close()


def _broadcast(msg: Message) -> None:
    """Best-effort real-time push so the UI can refresh unread counts.

    When the message belongs to a project, broadcast only to that project's
    members so non-members (e.g. join-request applicants) don't see it.
    """
    import logging
    _log = logging.getLogger(__name__)
    try:
        payload = {
            "id": msg.id,
            "body": msg.body,
            "category": msg.category.value if hasattr(msg.category, "value") else msg.category,
            "level": msg.level.value if hasattr(msg.level, "value") else msg.level,
            "title": msg.title,
            "link": msg.link,
            "project_id": msg.project_id,
            "recipient_id": msg.recipient_id,
            "read": False,
            "resolved": bool(msg.resolved),
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

        if msg.recipient_id is not None:
            from app.api.ws import manager
            manager.send_to_user(msg.recipient_id, "message_new", payload)
        elif msg.project_id is not None:
            from app.api.ws import broadcast_sync_to_project
            broadcast_sync_to_project(msg.project_id, "message_new", payload)
        else:
            from app.api.ws import broadcast_sync
            broadcast_sync("message_new", payload)
    except Exception:
        # Messaging must never break the caller's main flow.
        _log.warning("Failed to broadcast message_new for msg #%s", msg.id, exc_info=True)


def visible_messages(
    db: Session,
    *,
    user_id: int,
    include_dismissed: bool = False,
) -> Query:
    """Return the messages visible to one user.

    Explicitly addressed messages are visible only to their recipient. Broadcast
    project messages are visible only to project members, while global broadcasts
    remain visible to every authenticated user.
    """
    member_project_ids = db.query(ProjectMember.project_id).filter(
        ProjectMember.user_id == user_id
    )
    q = db.query(Message).filter(or_(
        Message.recipient_id == user_id,
        and_(
            Message.recipient_id.is_(None),
            or_(
                Message.project_id.is_(None),
                Message.project_id.in_(member_project_ids),
            ),
        ),
    ))
    if not include_dismissed:
        dismissed_ids = db.query(MessageRead.message_id).filter(
            MessageRead.user_id == user_id,
            MessageRead.dismissed_at.is_not(None),
        )
        q = q.filter(~Message.id.in_(dismissed_ids))
    return q


def unread_count(
    db: Session,
    project_id: int | None = None,
    recipient_id: int | None = None,
    user_id: int | None = None,
) -> int:
    """Count visible messages not yet read by *user_id*.

    Uses per-user ``MessageRead`` receipts exclusively — the legacy global
    ``Message.read`` column is intentionally ignored here so one user's
    read-action never affects another user's badge.
    """
    q = (
        visible_messages(db, user_id=user_id)
        if user_id is not None
        else db.query(Message)
    )
    if project_id is not None:
        q = q.filter(Message.project_id == project_id)
    if recipient_id is not None and user_id is None:
        q = q.filter(
            (Message.recipient_id == recipient_id) | (Message.recipient_id.is_(None))
        )
    if user_id is not None:
        read_ids = db.query(MessageRead.message_id).filter(
            MessageRead.user_id == user_id
        )
        q = q.filter(~Message.id.in_(read_ids))
    return q.count()


def resolve_by_link(link_prefix: str) -> None:
    """Mark messages whose ``link`` starts with *link_prefix* as resolved.

    Call this when a review is approved/rejected or a join request is handled,
    so other project members can see that the action has already been taken.
    """
    db = SessionLocal()
    try:
        updated = (
            db.query(Message)
            .filter(
                Message.link.startswith(link_prefix),
                Message.resolved == False,  # noqa: E712
            )
            .update({Message.resolved: True}, synchronize_session=False)
        )
        if updated:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
