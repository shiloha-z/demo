"""Message center API with per-user visibility, read and dismissal state."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import Message, MessageRead, User
from app.services import message_service as msg

router = APIRouter(prefix="/api", tags=["Messages"])


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient_id: int | None = None
    project_id: int | None = None
    category: str
    level: str
    title: str
    body: str
    link: str
    read: bool
    resolved: bool = False
    created_at: str | None = None

class ReadAllResponse(BaseModel):
    ok: bool = True


def _serialize_message(message: Message, *, read: bool) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        recipient_id=message.recipient_id,
        project_id=message.project_id,
        category=message.category.value if hasattr(message.category, "value") else message.category,
        level=message.level.value if hasattr(message.level, "value") else message.level,
        title=message.title,
        body=message.body,
        link=message.link,
        read=read,
        resolved=bool(message.resolved),
        created_at=message.created_at.isoformat() if message.created_at else None,
    )


def _visible_message(db: Session, user_id: int, message_id: int) -> Message:
    message = msg.visible_messages(db, user_id=user_id).filter(
        Message.id == message_id
    ).first()
    if not message:
        # Do not reveal whether an inaccessible message exists.
        raise HTTPException(status_code=404, detail="Message not found")
    return message


@router.get("/messages", response_model=list[MessageResponse])
def list_messages(
    project_id: int | None = Query(None, description="按项目过滤，留空则全部"),
    unread_only: bool = Query(False, description="仅返回未读"),
    category: str | None = Query(None, description="system/task/review/version/member"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    before_id: int | None = Query(None, gt=0, description="仅返回此 ID 之前的消息"),
):
    query = msg.visible_messages(db, user_id=user.id)
    if project_id is not None:
        query = query.filter(Message.project_id == project_id)
    if unread_only:
        read_message_ids = db.query(MessageRead.message_id).filter(
            MessageRead.user_id == user.id
        )
        query = query.filter(~Message.id.in_(read_message_ids))
    if category:
        query = query.filter(Message.category == category)
    # Direct service-level tests call endpoint functions without FastAPI's
    # dependency resolver, in which case the default is a Query object.
    if isinstance(before_id, int):
        query = query.filter(Message.id < before_id)

    messages = query.order_by(Message.id.desc()).limit(limit).all()
    message_ids = [message.id for message in messages]
    read_ids: set[int] = set()
    if message_ids:
        read_ids = {
            row[0]
            for row in db.query(MessageRead.message_id).filter(
                MessageRead.user_id == user.id,
                MessageRead.message_id.in_(message_ids),
            ).all()
        }
    return [
        _serialize_message(message, read=message.id in read_ids)
        for message in messages
    ]


@router.get("/messages/unread-count")
def unread_message_count(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"count": msg.unread_count(db, project_id=project_id, user_id=user.id)}


@router.post("/messages/{message_id}/read", response_model=MessageResponse)
def mark_read(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    message = _visible_message(db, user.id, message_id)
    receipt = db.query(MessageRead).filter(
        MessageRead.message_id == message.id,
        MessageRead.user_id == user.id,
    ).first()
    if not receipt:
        db.add(MessageRead(message_id=message.id, user_id=user.id))
        db.commit()
    return _serialize_message(message, read=True)


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    message = _visible_message(db, user.id, message_id)
    receipt = db.query(MessageRead).filter(
        MessageRead.message_id == message.id,
        MessageRead.user_id == user.id,
    ).first()
    now = datetime.now(timezone.utc)
    if receipt:
        receipt.dismissed_at = now
    else:
        db.add(MessageRead(
            message_id=message.id,
            user_id=user.id,
            dismissed_at=now,
        ))
    db.commit()
    return {"message": "已删除"}


@router.delete("/messages")
def delete_all_messages(
    project_id: int | None = Query(None, description="按项目过滤，留空则全部"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    category: str | None = Query(None, description="仅隐藏指定分类"),
):
    query = msg.visible_messages(db, user_id=user.id)
    if project_id is not None:
        query = query.filter(Message.project_id == project_id)
    if category:
        query = query.filter(Message.category == category)
    message_ids = [row[0] for row in query.with_entities(Message.id).all()]
    if message_ids:
        now = datetime.now(timezone.utc)
        receipts = {
            receipt.message_id: receipt
            for receipt in db.query(MessageRead).filter(
                MessageRead.user_id == user.id,
                MessageRead.message_id.in_(message_ids),
            ).all()
        }
        for message_id in message_ids:
            receipt = receipts.get(message_id)
            if receipt:
                receipt.dismissed_at = now
            else:
                db.add(MessageRead(
                    message_id=message_id,
                    user_id=user.id,
                    dismissed_at=now,
                ))
        db.commit()
    return {"message": f"已删除 {len(message_ids)} 条消息", "count": len(message_ids)}


@router.post("/messages/read-all", response_model=ReadAllResponse)
def mark_all_read(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    already_read = db.query(MessageRead.message_id).filter(
        MessageRead.user_id == user.id
    )
    query = msg.visible_messages(db, user_id=user.id).filter(
        ~Message.id.in_(already_read)
    )
    if project_id is not None:
        query = query.filter(Message.project_id == project_id)
    message_ids = [row[0] for row in query.with_entities(Message.id).all()]
    db.add_all([
        MessageRead(message_id=message_id, user_id=user.id)
        for message_id in message_ids
    ])
    db.commit()
    return ReadAllResponse()
