import os
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, ChatMessage
from app.api.ws import broadcast_sync, broadcast_sync_to_project

router = APIRouter(prefix="/api", tags=["Chat"])

# File upload config
_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "chat"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
_ALLOWED_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".py", ".js", ".ts", ".vue", ".java", ".go", ".rs", ".c", ".cpp", ".h",
}


# ── Schemas ───────────────────────────────────────────────────────────

class ChatMessageResponse(BaseModel):
    id: int
    user_id: int
    username: str
    message: str
    project_id: int | None = None
    recipient_id: int | None = None
    created_at: datetime | None = None
    system: bool = False
    file_url: str = ""
    file_name: str = ""
    file_type: str = ""
    file_size: int = 0

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, msg) -> "ChatMessageResponse":
        return cls(
            id=msg.id,
            user_id=msg.user_id,
            username=msg.username,
            message=msg.message or "",
            project_id=msg.project_id,
            recipient_id=msg.recipient_id,
            created_at=msg.created_at,
            system=msg.user_id == 0,
            file_url=msg.file_url or "",
            file_name=msg.file_name or "",
            file_type=msg.file_type or "",
            file_size=msg.file_size or 0,
        )


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/chat/messages", response_model=list[ChatMessageResponse])
def get_messages(
    project_id: int,
    recipient_id: int | None = None,
    limit: int = 50,
    before_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get recent chat messages. Team chat by default; pass `recipient_id` for DM."""
    q = db.query(ChatMessage).filter(
        ChatMessage.project_id == project_id,
        ChatMessage.recipient_id == recipient_id,  # None = team, int = DM
    )
    # For private chat, also include messages the current user sent
    if recipient_id is not None:
        q = db.query(ChatMessage).filter(
            ChatMessage.project_id == project_id,
            ChatMessage.recipient_id.in_([recipient_id, user.id]),
            ChatMessage.user_id.in_([recipient_id, user.id]),
        )
    if before_id is not None:
        q = q.filter(ChatMessage.id < before_id)
    messages = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    return [ChatMessageResponse.from_orm_obj(m) for m in reversed(messages)]


@router.get("/chat/members")
def get_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return project members for @mention and DM selection."""
    from app.models.models import Project, ProjectMember
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    members = []
    # Owner
    owner = db.query(User).filter(User.id == project.owner_id).first()
    if owner and owner.id != user.id:
        members.append({"id": owner.id, "username": owner.username, "display_name": owner.display_name or owner.username, "role": "owner"})
    # Members
    rows = db.query(ProjectMember, User).join(User, ProjectMember.user_id == User.id).filter(
        ProjectMember.project_id == project_id
    ).all()
    for pm, u in rows:
        if u.id != user.id:
            members.append({"id": u.id, "username": u.username, "display_name": u.display_name or u.username, "role": pm.role.value if hasattr(pm.role, 'value') else str(pm.role)})
    return {"members": members}


@router.post("/chat/upload")
def upload_chat_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload a file for chat sharing. Returns file metadata."""
    # Validate size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 20 MB)")

    # Validate extension
    ext = Path(file.filename or "unknown").suffix.lower()
    if ext not in _ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {ext}")

    # Generate unique filename
    safe_name = str(uuid.uuid4()) + ext
    dest = _UPLOAD_DIR / safe_name

    # Save file
    content = file.file.read()
    dest.write_bytes(content)

    # Determine if image
    content_type = file.content_type or ""
    is_image = content_type in _ALLOWED_IMAGE_TYPES or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

    return {
        "file_url": f"/api/chat/file/{safe_name}",
        "file_name": file.filename or "unknown",
        "file_type": "image" if is_image else "file",
        "file_size": size,
    }


@router.post("/chat/messages", response_model=ChatMessageResponse)
def send_message(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    project_id: int = Form(...),
    recipient_id: int | None = Form(None),
    message: str = Form(""),
    file_url: str = Form(""),
    file_name: str = Form(""),
    file_type: str = Form(""),
    file_size: int = Form(0),
):
    """Send a chat message. Set `recipient_id` for private DM; omit for team chat."""
    message_text = message.strip()
    file_url_str = file_url.strip()
    file_name_str = file_name.strip()
    file_type_str = file_type.strip()

    if not message_text and not file_url_str:
        raise HTTPException(status_code=400, detail="Message or file is required")
    if len(message_text) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 chars)")

    msg = ChatMessage(
        user_id=user.id,
        username=user.username,
        project_id=project_id,
        recipient_id=recipient_id,
        message=message_text,
        file_url=file_url_str,
        file_name=file_name_str,
        file_type=file_type_str,
        file_size=file_size,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    resp = ChatMessageResponse.from_orm_obj(msg)
    payload = resp.model_dump(mode="json")
    if recipient_id is not None:
        # Private message: push to both participants only.
        from app.api.ws import manager
        manager.send_to_user(user.id, "chat_message", payload)
        manager.send_to_user(recipient_id, "chat_message", payload)
    else:
        broadcast_sync_to_project(project_id, "chat_message", payload)

    # Notify @mentioned users
    _notify_mentions(message_text, user, project_id, db)

    return resp


@router.get("/chat/online")
def get_online_users(
    project_id: int | None = None,
    user: User = Depends(get_current_user),
):
    """Get list of currently online users. Optionally filter by project."""
    from app.api.ws import manager
    if project_id is not None:
        return {"online_users": manager.get_online_users_in_project(project_id)}
    return {"online_users": manager.get_online_users()}


@router.get("/chat/file/{filename}")
def serve_chat_file(filename: str):
    """Serve an uploaded chat file."""
    file_path = _UPLOAD_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Determine MIME type
    ext = file_path.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
    }
    media_type = mime_map.get(ext, "application/octet-stream")
    return FileResponse(str(file_path), media_type=media_type)


# ── Helpers ────────────────────────────────────────────────────────────────

def _notify_mentions(text: str, sender: User, project_id: int, db: Session) -> None:
    """Push message-centre notifications for every @username in *text*."""
    import re
    mentioned = set(re.findall(r"@(\w+)", text))
    if not mentioned:
        return
    from app.models.models import Project
    from app.services import message_service as msg
    from app.models.models import MessageCategory, MessageLevel
    project = db.query(Project).filter(Project.id == project_id).first()
    project_name = project.name if project else f"项目 #{project_id}"
    for username in mentioned:
        target = db.query(User).filter(User.username == username).first()
        if target and target.id != sender.id:
            try:
                msg.push(
                    title=f"{sender.username} @ 了你",
                    body=f"在「{project_name}」的聊天中提到了你",
                    category=MessageCategory.SYSTEM,
                    level=MessageLevel.INFO,
                    project_id=project_id,
                    recipient_id=target.id,
                    link="/dashboard",
                )
            except Exception:
                pass
