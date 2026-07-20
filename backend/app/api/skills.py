from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Skill
from app.services import skillhub_service

router = APIRouter(prefix="/api/skills", tags=["Skills"])


# ── Schemas ───────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    prompt_content: str = Field(default="")


class SkillUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    prompt_content: str = Field(default="")


class SkillResponse(BaseModel):
    id: int
    name: str
    description: str
    prompt_content: str
    source: str = "local"
    source_id: str = ""
    source_url: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class SkillHubSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    category: str = Field(default="", max_length=100)
    method: str = Field(default="hybrid", pattern="^(hybrid|embedding|fulltext)$")


class SkillHubImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    prompt_content: str = Field(default="")
    source_id: str = Field(..., min_length=1, max_length=300)
    source_url: str = Field(default="", max_length=1000)


def _skillhub_error(exc: skillhub_service.SkillHubError) -> HTTPException:
    status_code = 503 if "not configured" in str(exc).lower() else 502
    return HTTPException(status_code=status_code, detail=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    skills = db.query(Skill).filter(Skill.creator_id == user.id).order_by(Skill.updated_at.desc()).all()
    return skills


@router.get("/skillhub/status")
def skillhub_status(user: User = Depends(get_current_user)):
    """Expose configuration state without exposing the configured API key."""
    return {"configured": skillhub_service.configured()}


@router.post("/skillhub/search")
def search_skillhub(
    req: SkillHubSearchRequest,
    user: User = Depends(get_current_user),
):
    """Proxy a SkillHub semantic search through the backend."""
    try:
        return skillhub_service.search_skills(
            req.query,
            limit=req.limit,
            category=req.category,
            method=req.method,
        )
    except skillhub_service.SkillHubError as exc:
        raise _skillhub_error(exc) from exc


@router.get("/skillhub/catalog")
def skillhub_catalog(
    limit: int = 20,
    offset: int = 0,
    sort: str = "score",
    category: str = "",
    user: User = Depends(get_current_user),
):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    if sort not in {"score", "stars", "recent", "composite"}:
        raise HTTPException(status_code=422, detail="Unsupported SkillHub sort")
    try:
        return skillhub_service.browse_catalog(
            limit=limit,
            offset=offset,
            sort=sort,
            category=category,
        )
    except skillhub_service.SkillHubError as exc:
        raise _skillhub_error(exc) from exc


@router.post("/skillhub/import", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def import_skillhub_skill(
    req: SkillHubImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Copy a reviewed SkillHub result into this user's local skill library."""
    existing = db.query(Skill).filter(
        Skill.creator_id == user.id,
        Skill.source == "skillhub",
        Skill.source_id == req.source_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This SkillHub skill is already imported")
    skill = Skill(
        creator_id=user.id,
        name=req.name,
        description=req.description,
        prompt_content=req.prompt_content,
        source="skillhub",
        source_id=req.source_id,
        source_url=req.source_url,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.get("/{skill_id}", response_model=SkillResponse)
def get_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.creator_id == user.id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(
    req: SkillCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = Skill(
        creator_id=user.id,
        name=req.name,
        description=req.description,
        prompt_content=req.prompt_content,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.put("/{skill_id}", response_model=SkillResponse)
def update_skill(
    skill_id: int,
    req: SkillUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.creator_id == user.id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill.name = req.name
    skill.description = req.description
    skill.prompt_content = req.prompt_content
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}")
def delete_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.creator_id == user.id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    return {"message": "Deleted"}
