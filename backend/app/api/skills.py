from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Skill

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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    skills = db.query(Skill).order_by(Skill.updated_at.desc()).all()
    return skills


@router.get("/{skill_id}", response_model=SkillResponse)
def get_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
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
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
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
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    return {"message": "Deleted"}
