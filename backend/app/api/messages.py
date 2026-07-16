"""Message center API.

Endpoints for listing, unread-counting and marking messages as read.
Messages are system/project-level broadcasts; `recipient_id` is reserved for
future per-user delivery (see Message model) but not filtered here yet.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Message, MessageCategory, MessageLevel, MessageRead

router = APIRouter(prefix="/api", tags=["Messages"])


# ── Schemas ───────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    id: int
    recipient_id: int | None = None
    project_id: int | None = None
    category: str
    level: str
    title: str
    body: str
    link: str
    read: bool
    created_at: str | None = None

    class Config:
        from_attributes = True


class ReadAllResponse(BaseModel):
    ok: bool = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/messages", response_model=list[MessageResponse])
def list_messages(
    project_id: int | None = Query(None, description="按项目过滤，留空则全部"),
    unread_only: bool = Query(False, description="仅返回未读"),
    category: str | None = Query(None, description="system/task/review/version/member"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Message)
    if project_id is not None:
        q = q.filter(Message.project_id == project_id)
    if unread_only:
        read_message_ids = db.query(MessageRead.message_id).filter(
            MessageRead.user_id == user.id
        )
        q = q.filter(
            Message.read == False,  # noqa: E712
            ~Message.id.in_(read_message_ids),
        )
    if category:
        q = q.filter(Message.category == category)
    messages = q.order_by(Message.created_at.desc()).limit(limit).all()
    message_ids = [m.id for m in messages]
    read_ids = set()
    if message_ids:
        read_ids = {
            row[0] for row in db.query(MessageRead.message_id).filter(
                MessageRead.user_id == user.id,
                MessageRead.message_id.in_(message_ids),
            ).all()
        }
    return [
        MessageResponse(
            id=m.id,
            recipient_id=m.recipient_id,
            project_id=m.project_id,
            category=m.category.value if hasattr(m.category, "value") else m.category,
            level=m.level.value if hasattr(m.level, "value") else m.level,
            title=m.title,
            body=m.body,
            link=m.link,
            read=bool(m.read) or m.id in read_ids,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in messages
    ]


@router.get("/messages/unread-count")
def unread_message_count(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services import message_service as msg

    count = msg.unread_count(db, project_id=project_id, user_id=user.id)
    return {"count": count}


@router.post("/messages/{message_id}/read", response_model=MessageResponse)
def mark_read(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Message not found")
    receipt = db.query(MessageRead).filter(
        MessageRead.message_id == m.id,
        MessageRead.user_id == user.id,
    ).first()
    if not receipt:
        db.add(MessageRead(message_id=m.id, user_id=user.id))
        db.commit()
    return MessageResponse(
        id=m.id,
        recipient_id=m.recipient_id,
        project_id=m.project_id,
        category=m.category.value if hasattr(m.category, "value") else m.category,
        level=m.level.value if hasattr(m.level, "value") else m.level,
        title=m.title,
        body=m.body,
        link=m.link,
        read=True,
        created_at=m.created_at.isoformat() if m.created_at else None,
    )


@router.post("/messages/read-all", response_model=ReadAllResponse)
def mark_all_read(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Message).filter(Message.read == False)  # noqa: E712
    if project_id is not None:
        q = q.filter(Message.project_id == project_id)
    message_ids = [row[0] for row in q.with_entities(Message.id).all()]
    existing = set()
    if message_ids:
        existing = {
            row[0] for row in db.query(MessageRead.message_id).filter(
                MessageRead.user_id == user.id,
                MessageRead.message_id.in_(message_ids),
            ).all()
        }
    db.add_all([
        MessageRead(message_id=message_id, user_id=user.id)
        for message_id in message_ids
        if message_id not in existing
    ])
    db.commit()
    return ReadAllResponse()
