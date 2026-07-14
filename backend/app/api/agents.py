from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User, Agent, AgentStatus

router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ── Schemas ───────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., min_length=1, max_length=100)
    model: str = Field(default="deepseek-chat")
    system_prompt: str = Field(default="")


class AgentResponse(BaseModel):
    id: int
    name: str
    role: str
    model: str
    system_prompt: str
    status: str

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[AgentResponse])
def list_agents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agents = db.query(Agent).all()
    return [AgentResponse.model_validate(a) for a in agents]


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    req: AgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = Agent(
        creator_id=user.id,
        name=req.name,
        role=req.role,
        model=req.model,
        system_prompt=req.system_prompt,
        status=AgentStatus.IDLE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
    return {"message": "Deleted"}
