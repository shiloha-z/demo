import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import hash_password, verify_password, create_access_token, get_current_user
from app.models.models import User

router = APIRouter(prefix="/api/auth", tags=["Auth"])

_AVATAR_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "avatars"
_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
_MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
_AVATAR_URL_PREFIX = "/api/auth/profile/avatar"


def _avatar_url(value: str | None) -> str:
    """Return the canonical public URL, including for legacy stored URLs."""
    if not value:
        return ""
    filename = Path(value.split("?", 1)[0]).name
    return f"{_AVATAR_URL_PREFIX}/{filename}" if filename else ""


def _image_format(content: bytes) -> str | None:
    """Validate the image signature without trusting the extension or MIME type."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


# ── Schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
    display_name: str = Field(default="")


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str
    display_name: str
    user_id: int


class ProfileResponse(BaseModel):
    username: str
    display_name: str
    email: str = ""
    phone: str = ""
    bio: str = ""
    avatar_url: str = ""

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=30)
    bio: str = Field(default="", max_length=500)


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.username, user.display_name)
    return AuthResponse(token=token, username=user.username, display_name=user.display_name, user_id=user.id)


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")

    token = create_access_token(user.id, user.username, user.display_name)
    return AuthResponse(token=token, username=user.username, display_name=user.display_name, user_id=user.id)


@router.get("/profile", response_model=ProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
):
    """Return current user's profile."""
    return ProfileResponse(
        username=user.username,
        display_name=user.display_name or "",
        email=user.email or "",
        phone=user.phone or "",
        bio=user.bio or "",
        avatar_url=_avatar_url(user.avatar_url),
    )


@router.put("/profile", response_model=ProfileResponse)
def update_profile(
    req: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's profile."""
    user.display_name = req.display_name
    user.email = req.email
    user.phone = req.phone
    user.bio = req.bio
    db.commit()
    db.refresh(user)
    return ProfileResponse(
        username=user.username,
        display_name=user.display_name or "",
        email=user.email or "",
        phone=user.phone or "",
        bio=user.bio or "",
        avatar_url=_avatar_url(user.avatar_url),
    )


@router.post("/profile/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a profile avatar image. Max 2 MB."""
    # Validate type first
    ext = Path(file.filename or "avatar.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(status_code=400, detail="不支持的图片格式，请使用 PNG/JPG/GIF/WebP")

    # Read content and validate size
    content = file.file.read()
    if len(content) > _MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="头像文件不能超过 2 MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="头像文件不能为空")

    actual_format = _image_format(content)
    if not actual_format:
        raise HTTPException(status_code=400, detail="上传文件不是有效的图片")
    allowed_extensions = {
        "png": {".png"},
        "jpeg": {".jpg", ".jpeg"},
        "gif": {".gif"},
        "webp": {".webp"},
    }
    if ext not in allowed_extensions[actual_format]:
        raise HTTPException(status_code=400, detail="图片内容与文件扩展名不一致")

    old_path = _AVATAR_DIR / Path((user.avatar_url or "").split("?", 1)[0]).name
    safe_name = f"{user.id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = _AVATAR_DIR / safe_name
    dest.write_bytes(content)

    user.avatar_url = f"{_AVATAR_URL_PREFIX}/{safe_name}"
    try:
        db.commit()
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    if old_path != dest and old_path.is_file():
        try:
            os.remove(old_path)
        except OSError:
            pass

    return {"avatar_url": user.avatar_url}


@router.get("/profile/avatar/{filename}")
@router.get("/avatar/{filename}", include_in_schema=False)
def serve_avatar(filename: str):
    """Serve an uploaded avatar file."""
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Avatar not found")
    file_path = _AVATAR_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")
    ext = file_path.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    from fastapi.responses import FileResponse
    return FileResponse(
        str(file_path),
        media_type=mime_map.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )
