"""调试用管理后台（无鉴权，仅本地使用）。

提供对账号 / 项目 / Agent 三类资源的查看列表、详情与删除能力。
删除逻辑独立内联实现，与现有 projects.delete_project / agents.delete_agent
的级联顺序、物理工作区清理保持一致，且不依赖 Depends(get_current_user)，
因此不会污染主应用的鉴权路径。

⚠️ 该路由没有任何访问控制，仅用于本地调试。生产环境上线前务必移除注册
（backend/app/main.py 中的 admin_router）或补齐 is_admin 校验。
"""
import logging
import os
import shutil

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc

from app.core.database import get_db
from app.models.models import (
    User, Project, ProjectMember, JoinRequest, Agent, AgentStatus, Skill,
    Task, TaskStatus, Review, ReviewStatus, ReviewVote, ReviewReviewer,
    ReviewRound, Version, ChatMessage, Message, MessageRead, AuditLog,
)

router = APIRouter(prefix="/api/admin", tags=["AdminDebug"])
logger = logging.getLogger(__name__)


# ── 账号 ──────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    q: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(User.username.ilike(like) | User.display_name.ilike(like))
    users = query.order_by(User.id.desc()).limit(limit).all()
    items = []
    for u in users:
        items.append({
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name or "",
            "email": u.email or "",
            "project_count": db.query(func.count(Project.id)).filter(Project.owner_id == u.id).scalar() or 0,
            "agent_count": db.query(func.count(Agent.id)).filter(Agent.creator_id == u.id).scalar() or 0,
            "skill_count": db.query(func.count(Skill.id)).filter(Skill.creator_id == u.id).scalar() or 0,
        })
    return {"total": len(items), "items": items}


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    owned_projects = [
        {"id": p.id, "name": p.name, "project_id": p.project_id}
        for p in db.query(Project).filter(Project.owner_id == u.id).all()
    ]
    created_agents = [
        {"id": a.id, "name": a.name, "role": a.role}
        for a in db.query(Agent).filter(Agent.creator_id == u.id).all()
    ]
    task_count = db.query(func.count(Task.id)).filter(
        Task.project_id.in_(db.query(Project.id).filter(Project.owner_id == u.id))
    ).scalar() or 0
    review_count = db.query(func.count(ReviewReviewer.id)).filter(
        ReviewReviewer.user_id == u.id
    ).scalar() or 0
    audit_count = db.query(func.count(AuditLog.id)).filter(AuditLog.actor_id == u.id).scalar() or 0
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or "",
        "email": u.email or "",
        "phone": u.phone or "",
        "bio": u.bio or "",
        "avatar_url": u.avatar_url or "",
        "owned_projects": owned_projects,
        "created_agents": created_agents,
        "stats": {
            "project_count": len(owned_projects),
            "agent_count": len(created_agents),
            "task_count": task_count,
            "review_count": review_count,
            "audit_count": audit_count,
        },
    }


def _delete_user_data(uid: int, db: Session) -> None:
    """级联删除用户及其全部关联数据（对齐现有 delete 逻辑）。"""
    # 1) 删除该用户拥有的项目（含物理工作区）
    owned = db.query(Project).filter(Project.owner_id == uid).all()
    for p in owned:
        _delete_project_record(p, db)

    # 2) 用户创建的 Agent
    for a in db.query(Agent).filter(Agent.creator_id == uid).all():
        _delete_agent_record(a, db)

    # 3) 用户创建的技能
    db.query(Skill).filter(Skill.creator_id == uid).delete(synchronize_session=False)

    # 4) 参与但非拥有的关联行
    db.query(ProjectMember).filter(ProjectMember.user_id == uid).delete(synchronize_session=False)
    db.query(JoinRequest).filter(JoinRequest.user_id == uid).delete(synchronize_session=False)
    db.query(ReviewReviewer).filter(ReviewReviewer.user_id == uid).delete(synchronize_session=False)
    db.query(ReviewVote).filter(ReviewVote.user_id == uid).delete(synchronize_session=False)
    db.query(ChatMessage).filter(ChatMessage.user_id == uid).delete(synchronize_session=False)
    db.query(MessageRead).filter(MessageRead.user_id == uid).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(synchronize_session=False)
    db.query(Message).filter(Message.recipient_id == uid).delete(synchronize_session=False)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    username = u.username
    _delete_user_data(user_id, db)
    db.delete(u)
    db.commit()
    return {"message": f"账号「{username}」已删除"}


# ── 项目 ──────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    q: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
):
    query = db.query(Project).options(joinedload(Project.owner))
    if q:
        like = f"%{q}%"
        query = query.filter(Project.name.ilike(like) | Project.project_id.ilike(like))
    projects = query.order_by(desc(Project.created_at)).limit(limit).all()
    items = []
    for p in projects:
        items.append({
            "id": p.id,
            "project_id": p.project_id,
            "name": p.name,
            "owner_id": p.owner_id,
            "owner_name": p.owner.username if p.owner else "",
            "task_count": db.query(func.count(Task.id)).filter(Task.project_id == p.id).scalar() or 0,
            "member_count": db.query(func.count(ProjectMember.id)).filter(ProjectMember.project_id == p.id).scalar() or 0,
            "workspace_path": p.workspace_path or "",
            "created_at": p.created_at.isoformat() if p.created_at else "",
        })
    return {"total": len(items), "items": items}


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).options(joinedload(Project.owner)).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    members = [
        {"id": m.id, "user_id": m.user_id, "role": m.role.value if hasattr(m.role, "value") else str(m.role)}
        for m in db.query(ProjectMember).filter(ProjectMember.project_id == p.id).all()
    ]
    tasks = [
        {"id": t.id, "title": t.title, "status": t.status.value if hasattr(t.status, "value") else str(t.status)}
        for t in db.query(Task).filter(Task.project_id == p.id).order_by(Task.id.desc()).all()
    ]
    return {
        "id": p.id,
        "project_id": p.project_id,
        "name": p.name,
        "description": p.description or "",
        "owner_id": p.owner_id,
        "owner_name": p.owner.username if p.owner else "",
        "workspace_path": p.workspace_path or "",
        "members": members,
        "tasks": tasks,
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


def _delete_project_record(project, db: Session) -> None:
    """物理 + 逻辑删除单个项目记录（复用自 projects.delete_project 的顺序）。"""
    project_id = project.id
    stuck_agent_ids = [
        row[0] for row in
        db.query(Agent.id).join(Task, Task.agent_id == Agent.id).filter(
            Task.project_id == project_id,
            Agent.status == AgentStatus.WORKING,
        ).distinct().all()
    ]
    task_worktrees = [
        task.worktree_path for task in db.query(Task).filter(Task.project_id == project_id).all()
        if task.worktree_path
    ]
    review_ids = [
        row[0] for row in
        db.query(Review.id).filter(Review.project_id == project_id).all()
    ]
    if review_ids:
        db.query(ReviewVote).filter(ReviewVote.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(ReviewReviewer).filter(ReviewReviewer.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(ReviewRound).filter(ReviewRound.review_id.in_(review_ids)).delete(synchronize_session=False)
    db.query(Review).filter(Review.project_id == project_id).delete()
    db.query(Version).filter(Version.project_id == project_id).delete()
    db.query(Task).filter(Task.project_id == project_id).delete()
    db.query(JoinRequest).filter(JoinRequest.project_id == project_id).delete()
    db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete()
    db.query(ChatMessage).filter(ChatMessage.project_id == project_id).delete()
    message_ids = [
        row[0] for row in db.query(Message.id).filter(Message.project_id == project_id).all()
    ]
    if message_ids:
        db.query(MessageRead).filter(MessageRead.message_id.in_(message_ids)).delete(synchronize_session=False)
    db.query(Message).filter(Message.project_id == project_id).delete()

    if stuck_agent_ids:
        db.query(Agent).filter(Agent.id.in_(stuck_agent_ids)).update(
            {Agent.status: AgentStatus.IDLE}, synchronize_session=False
        )

    project_workspace = project.workspace_path
    db.delete(project)
    db.commit()

    # 物理清理工作目录
    try:
        for worktree_path in task_worktrees:
            try:
                from app.services import git_service
                git_service.remove_task_worktree(project_workspace, worktree_path)
            except Exception:
                logger.warning("worktree cleanup failed for project %s", project_id)
        if project_workspace and os.path.isdir(project_workspace):
            def _on_rm_error(func, path, exc_info):
                import stat
                os.chmod(path, stat.S_IWRITE)
                func(path)
            shutil.rmtree(project_workspace, onerror=_on_rm_error)
    except OSError:
        logger.exception("Workspace cleanup failed for deleted project %s", project_id)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    name = p.name
    _delete_project_record(p, db)
    return {"message": f"项目「{name}」已删除"}


# ── Agent ─────────────────────────────────────────────────────────────

@router.get("/agents")
def list_agents(
    db: Session = Depends(get_db),
    q: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
):
    query = db.query(Agent).options(joinedload(Agent.creator))
    if q:
        like = f"%{q}%"
        query = query.filter(Agent.name.ilike(like) | Agent.role.ilike(like))
    agents = query.order_by(Agent.id.desc()).limit(limit).all()
    items = []
    for a in agents:
        items.append({
            "id": a.id,
            "name": a.name,
            "role": a.role,
            "model": a.model,
            "runner_type": a.runner_type or "crewai",
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "creator_id": a.creator_id,
            "creator_name": a.creator.display_name or a.creator.username if a.creator else "",
            "task_count": db.query(func.count(Task.id)).filter(Task.agent_id == a.id).scalar() or 0,
        })
    return {"total": len(items), "items": items}


@router.get("/agents/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    a = db.query(Agent).options(joinedload(Agent.creator)).filter(Agent.id == agent_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    tasks = [
        {"id": t.id, "title": t.title, "status": t.status.value if hasattr(t.status, "value") else str(t.status)}
        for t in db.query(Task).filter(Task.agent_id == a.id).order_by(Task.id.desc()).all()
    ]
    return {
        "id": a.id,
        "name": a.name,
        "role": a.role,
        "model": a.model,
        "runner_type": a.runner_type or "crewai",
        "system_prompt": a.system_prompt or "",
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "creator_id": a.creator_id,
        "creator_name": a.creator.display_name or a.creator.username if a.creator else "",
        "tasks": tasks,
    }


def _delete_agent_record(agent, db: Session) -> None:
    """级联删除单个 Agent 记录（复用自 agents.delete_agent 的顺序）。"""
    agent_id = agent.id
    task_ids = [
        row[0] for row in db.query(Task.id).filter(Task.agent_id == agent_id).all()
    ]
    if task_ids:
        review_ids = [
            row[0] for row in db.query(Review.id).filter(Review.task_id.in_(task_ids)).all()
        ]
        if review_ids:
            db.query(ReviewVote).filter(ReviewVote.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(ReviewReviewer).filter(ReviewReviewer.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(ReviewRound).filter(ReviewRound.review_id.in_(review_ids)).delete(synchronize_session=False)
            db.query(Version).filter(Version.review_id.in_(review_ids)).update(
                {Version.review_id: None}, synchronize_session=False
            )
            db.query(Review).filter(Review.id.in_(review_ids)).delete(synchronize_session=False)
        db.query(Task).filter(Task.agent_id == agent_id).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    a = db.query(Agent).filter(Agent.id == agent_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    name = a.name
    _delete_agent_record(a, db)
    return {"message": f"Agent「{name}」已删除"}
