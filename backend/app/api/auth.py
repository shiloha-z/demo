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
        avatar_url=user.avatar_url or "",
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
        avatar_url=user.avatar_url or "",
    )


@router.post("/profile/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a profile avatar image. Max 2 MB."""
    # Validate size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > _MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="头像文件不能超过 2 MB")

    # Validate type
    ext = Path(file.filename or "avatar.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(status_code=400, detail="不支持的图片格式，请使用 PNG/JPG/GIF/WebP")

    # Remove old avatar if exists
    if user.avatar_url:
        old_path = _AVATAR_DIR / Path(user.avatar_url).name
        if old_path.exists():
            os.remove(old_path)

    # Save new avatar
    safe_name = f"{user.id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = _AVATAR_DIR / safe_name
    content = file.file.read()
    dest.write_bytes(content)

    user.avatar_url = f"/api/auth/avatar/{safe_name}"
    db.commit()

    return {"avatar_url": user.avatar_url}


@router.get("/profile/avatar/{filename}")
def serve_avatar(filename: str):
    """Serve an uploaded avatar file."""
    file_path = _AVATAR_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")
    ext = file_path.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    from fastapi.responses import FileResponse
    return FileResponse(str(file_path), media_type=mime_map.get(ext, "application/octet-stream"))
