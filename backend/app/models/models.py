from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)

from app.core.database import Base


# ── Enums ─────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"


class TaskStatus(str, Enum):
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    PAUSED = "paused"            # 已暂停
    REVIEWING = "reviewing"      # 待审核（Agent 执行完毕，等待人工审查）
    APPROVED = "approved"        # 已通过（审查通过，已合并）
    REJECTED = "rejected"        # 已驳回（审查驳回）
    FAILED = "failed"            # 执行失败


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProjectRole(str, Enum):
    OWNER = "owner"      # 项目主管 — 完全控制，可转让
    ADMIN = "admin"      # 管理员 — 管理成员（除 owner），管理任务/审查
    MEMBER = "member"    # 一般成员 — 查看、创建任务、聊天


# ── Tables ────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    display_name = Column(String(100), default="")

    agents = relationship("Agent", back_populates="creator")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workspace_path = Column(String(500), default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    owner = relationship("User")

    @property
    def owner_name(self) -> str:
        return self.owner.username if self.owner else ""


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(SAEnum(ProjectRole), default=ProjectRole.MEMBER, nullable=False)
    joined_at = Column(DateTime, default=_now)

    user = relationship("User")
    project = relationship("Project")


class JoinStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class JoinRequest(Base):
    __tablename__ = "join_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(50), nullable=False)
    status = Column(SAEnum(JoinStatus), default=JoinStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=_now)
    reviewed_at = Column(DateTime, nullable=True)

    user = relationship("User")
    project = relationship("Project")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(String(100), nullable=False)       # code_gen / reviewer / security
    model = Column(String(100), default="deepseek-chat")  # LLM model name
    runner_type = Column(String(50), default="crewai")  # crewai / claude_code / opencode
    system_prompt = Column(Text, default="")
    status = Column(SAEnum(AgentStatus), default=AgentStatus.IDLE)

    creator = relationship("User", back_populates="agents")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING)
    archived = Column(Boolean, default=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    agent = relationship("Agent")
    project = relationship("Project")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    diff_content = Column(Text, default="")
    agent_review_summary = Column(Text, default="")
    status = Column(SAEnum(ReviewStatus), default=ReviewStatus.PENDING)
    human_feedback = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class Version(Base):
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    commit_hash = Column(String(40), nullable=False)
    commit_message = Column(String(500), default="")
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=True)
    created_at = Column(DateTime, default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(50), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    message = Column(Text, nullable=False, default="")
    file_url = Column(String(500), default="")
    file_name = Column(String(200), default="")
    file_type = Column(String(50), default="")   # "image", "file"
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
