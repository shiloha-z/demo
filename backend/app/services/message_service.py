"""Message center service.

Thin helper around the `Message` table. Designed to be inserted into existing
business flows (agent_runner, reviews, versions) without altering their logic.

`push` optionally broadcasts a `message_new` WebSocket event so the frontend
can refresh its unread badge in real time — reusing the existing broadcast_sync,
no new protocol.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.models import (
    Message,
    MessageCategory,
    MessageLevel,
    Project,
    User,
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
    try:
        payload = {
            "id": msg.id,
            "category": msg.category.value if hasattr(msg.category, "value") else msg.category,
            "level": msg.level.value if hasattr(msg.level, "value") else msg.level,
            "title": msg.title,
            "project_id": msg.project_id,
            "recipient_id": msg.recipient_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

        if msg.project_id is not None:
            from app.api.ws import broadcast_sync_to_project
            broadcast_sync_to_project(msg.project_id, "message_new", payload)
        else:
            from app.api.ws import broadcast_sync
            broadcast_sync("message_new", payload)
    except Exception:
        # Messaging must never break the caller's main flow.
        pass


def unread_count(db: Session, project_id: int | None = None, recipient_id: int | None = None) -> int:
    q = db.query(Message).filter(Message.read == False)  # noqa: E712
    if project_id is not None:
        q = q.filter(Message.project_id == project_id)
    if recipient_id is not None:
        q = q.filter(
            (Message.recipient_id == recipient_id) | (Message.recipient_id.is_(None))
        )
    return q.count()
