import os, re, shutil, secrets, string
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from typing import List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc

from app.core.database import get_db
from app.core.config import settings
from app.core.auth import get_current_user
from app.models.models import User, Project, Task, TaskStatus, Review, Version, Agent, AgentStatus, ProjectMember, ProjectRole, JoinRequest, JoinStatus
from app.services import git_service as git

router = APIRouter(prefix="/api/projects", tags=["Projects"])


def _broadcast_project_update(action: str, project_id: int) -> None:
    """Notify all connected users that the project list changed."""
    from app.api.ws import broadcast_sync
    broadcast_sync("project_update", {"action": action, "project_id": project_id})


def _broadcast_file_change(project_id: int) -> None:
    from app.api.ws import broadcast_sync
    broadcast_sync("file_change", {"project_id": project_id})


# ── Schemas ───────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    workspace_name: str = Field(default="", max_length=100, description="工作空间文件夹名，留空则使用项目名")


class ProjectResponse(BaseModel):
    id: int
    project_id: str | None = None
    name: str
    description: str
    owner_id: int
    owner_name: str = ""
    workspace_path: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


# ── Helpers ───────────────────────────────────────────────────────────

def _sanitize_dirname(name: str) -> str:
    """Convert a display name into a safe directory name."""
    # Replace spaces & special chars with underscore, collapse runs
    safe = re.sub(r'[\\/:*?"<>| ]+', '_', name.strip())
    # Deduplicate underscores
    safe = re.sub(r'_+', '_', safe)
    # Strip leading/trailing underscores
    safe = safe.strip('_')
    return safe or 'project'


def _generate_project_id() -> str:
    """Generate a canonical project ID: PROJ-YYYYMMDD-XXXXXX."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"PROJ-{date_part}-{random_part}"


def _require_membership(project_id: int, user: User, db: Session) -> Project:
    """Get project and verify the user is a project member. Raises 404/403 otherwise."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Owner is always allowed
    if project.owner_id == user.id:
        return project
    # Check ProjectMember table
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="只有项目成员才能进行此操作")
    return project


def _get_workspace(project_id: int, user: User, db: Session) -> str:
    project = _require_membership(project_id, user, db)
    if not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    return project.workspace_path


# ── Project CRUD ──────────────────────────────────────────────────────

@router.get("", response_model=ProjectListResponse)
def list_projects(
    sort: str = Query(default="created_desc", description="created_desc | created_asc | updated_desc | name_asc | name_desc"),
    filter: str = Query(default="all", description="all | joined | owner | admin | member | other"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sort_map = {
        "created_desc": desc(Project.created_at),
        "created_asc": asc(Project.created_at),
        "updated_desc": desc(Project.updated_at),
        "name_asc": asc(Project.name),
        "name_desc": desc(Project.name),
    }
    order = sort_map.get(sort, desc(Project.created_at))
    q = db.query(Project).options(joinedload(Project.owner))

    # Filter by user's relationship to the project
    if filter == "joined":
        # Used by the global project switcher. A user may only enter projects
        # where they are the owner or have an explicit membership.
        joined_project_ids = [
            row[0] for row in
            db.query(ProjectMember.project_id).filter(
                ProjectMember.user_id == user.id,
            ).all()
        ]
        q = q.filter(
            (Project.owner_id == user.id) | Project.id.in_(joined_project_ids)
        )
    elif filter == "owner":
        q = q.filter(Project.owner_id == user.id)
    elif filter == "admin":
        admin_project_ids = [
            row[0] for row in
            db.query(ProjectMember.project_id).filter(
                ProjectMember.user_id == user.id,
                ProjectMember.role == ProjectRole.ADMIN,
            ).all()
        ]
        q = q.filter(Project.id.in_(admin_project_ids)) if admin_project_ids else q.filter(Project.id == -1)
    elif filter == "member":
        member_project_ids = [
            row[0] for row in
            db.query(ProjectMember.project_id).filter(
                ProjectMember.user_id == user.id,
                ProjectMember.role == ProjectRole.MEMBER,
            ).all()
        ]
        q = q.filter(Project.id.in_(member_project_ids)) if member_project_ids else q.filter(Project.id == -1)
    elif filter == "other":
        # Projects where user is NOT the owner and NOT a member
        all_my_project_ids = [
            row[0] for row in
            db.query(ProjectMember.project_id).filter(
                ProjectMember.user_id == user.id,
            ).all()
        ]
        q = q.filter(Project.owner_id != user.id)
        if all_my_project_ids:
            q = q.filter(Project.id.notin_(all_my_project_ids))

    projects = q.order_by(order).all()
    return ProjectListResponse(projects=[ProjectResponse.model_validate(p) for p in projects])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(req: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Generate unique project_id
    project_id = _generate_project_id()
    while db.query(Project).filter(Project.project_id == project_id).first():
        project_id = _generate_project_id()

    project = Project(name=req.name, description=req.description, owner_id=user.id, project_id=project_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    # Auto-add creator as project owner (skip if already exists)
    existing = db.query(ProjectMember).filter(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == user.id,
    ).first()
    if not existing:
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
        db.commit()

    # Workspace folder: use custom name if provided, otherwise sanitize project name
    dirname = _sanitize_dirname(req.workspace_name or req.name)
    workspace = os.path.abspath(os.path.join(settings.WORKSPACE_ROOT, dirname))
    # If the preferred name already exists, append project id as suffix
    if os.path.exists(workspace):
        workspace = os.path.abspath(os.path.join(settings.WORKSPACE_ROOT, f"{dirname}_{project.id}"))
    project.workspace_path = workspace
    db.commit()

    os.makedirs(workspace, exist_ok=True)
    try:
        from ..services import git_service
        git_service.init_repo(workspace)
    except Exception:
        pass

    # Reload with owner relationship to get owner_name
    db.refresh(project)
    response = ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        owner_id=project.owner_id,
        owner_name=project.owner.username if project.owner else "",
        workspace_path=project.workspace_path or "",
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    _broadcast_project_update("created", project.id)
    return response


# ── File management (MUST be before /{project_id}) ────────────────────

@router.get("/{project_id}/files")
def file_tree(
    project_id: int,
    path: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List project files from the master branch (approved state only)."""
    workspace = _get_workspace(project_id, user, db)
    try:
        nodes = git.list_files(workspace, path, ref="master")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"files": nodes}


@router.get("/{project_id}/file")
def read_file(
    project_id: int,
    path: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read a file from the master branch (approved state only)."""
    workspace = _get_workspace(project_id, user, db)
    try:
        content = git.read_file(workspace, path, ref="master")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}


def _touch_project(db: Session, project_id: int):
    """Update project's updated_at timestamp."""
    db.query(Project).filter(Project.id == project_id).update({"updated_at": datetime.now(timezone.utc)})
    db.commit()


@router.post("/{project_id}/file")
def create_file(
    project_id: int,
    path: str = Query(...),
    content: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = _get_workspace(project_id, user, db)
    try:
        target = git.write_file(workspace, path, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    git.commit(workspace, f"Create/update {path}")
    _touch_project(db, project_id)
    _broadcast_file_change(project_id)
    return {"path": path, "message": "File created"}


@router.post("/{project_id}/folder")
def create_folder(
    project_id: int,
    path: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = _get_workspace(project_id, user, db)
    try:
        target = git.create_folder(workspace, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    git.commit(workspace, f"Create folder {path}")
    _touch_project(db, project_id)
    _broadcast_file_change(project_id)
    return {"path": path, "message": "Folder created"}


@router.delete("/{project_id}/file")
def delete_file(
    project_id: int,
    path: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a file or folder from the project workspace."""
    workspace = _get_workspace(project_id, user, db)
    try:
        target = git.delete_path(workspace, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File or folder not found")
    git.commit(workspace, f"Delete {path}")
    _touch_project(db, project_id)
    _broadcast_file_change(project_id)
    return {"path": path, "message": "Deleted"}


@router.post("/{project_id}/upload")
async def upload_files(
    project_id: int,
    files: List[UploadFile] = File(...),
    path: str = Form(default=""),
    file_paths: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload one or more files into the project workspace.

    When ``file_paths`` is provided and its length matches ``files``,
    each file is placed at the corresponding relative path (used for folder upload).
    Otherwise, all files share the single ``path`` prefix (legacy file upload).
    """
    workspace = _get_workspace(project_id, user, db)
    uploaded = []
    use_per_file_paths = file_paths and len(file_paths) == len(files)

    for i, file in enumerate(files):
        original_filename = file.filename or "untitled"
        if use_per_file_paths:
            target_path = file_paths[i]
        else:
            dir_part = path if path else ""
            target_path = f"{dir_part}/{original_filename}".lstrip("/") if dir_part else original_filename

        # Sanitize
        full_path = os.path.normpath(os.path.join(workspace, target_path))
        if not full_path.startswith(os.path.normpath(workspace) + os.sep) and full_path != os.path.normpath(workspace):
            raise HTTPException(status_code=400, detail=f"Invalid path: {target_path}")

        content = await file.read()
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            git.upload_file(workspace, target_path, content)
        else:
            git.write_file(workspace, target_path, decoded)

        uploaded.append({"path": target_path, "filename": original_filename})

    _touch_project(db, project_id)
    git.commit(workspace, f"Upload {len(uploaded)} file(s)")
    _broadcast_file_change(project_id)
    return {"files": uploaded, "message": f"{len(uploaded)} file(s) uploaded"}


# ── Project detail + delete ─────────────────────────────────────────

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _require_membership(project_id, user, db)
    # Eager load owner for serialization
    db.refresh(project, attribute_names=["owner"])
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a project. Only the owner or admin can delete it."""
    project = _require_membership(project_id, user, db)

    # Check delete permission: owner or admin
    if project.owner_id != user.id:
        membership = db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ).first()
        if not membership or membership.role not in (ProjectRole.OWNER, ProjectRole.ADMIN):
            raise HTTPException(status_code=403, detail="只有项目主管或管理员才能删除项目")

    running_task = db.query(Task.id).filter(
        Task.project_id == project_id,
        Task.status == TaskStatus.RUNNING,
    ).first()
    if running_task:
        raise HTTPException(status_code=409, detail="Cannot delete a project while an agent task is running")

    # Find agents that are currently working on tasks in this project
    stuck_agent_ids = [
        row[0] for row in
        db.query(Agent.id).join(Task, Task.agent_id == Agent.id).filter(
            Task.project_id == project_id,
            Agent.status == AgentStatus.WORKING,
        ).distinct().all()
    ]

    # Delete associated records
    db.query(Review).filter(Review.project_id == project_id).delete()
    db.query(Version).filter(Version.project_id == project_id).delete()
    db.query(Task).filter(Task.project_id == project_id).delete()

    # Reset agents that were working on this project's tasks back to IDLE
    if stuck_agent_ids:
        db.query(Agent).filter(Agent.id.in_(stuck_agent_ids)).update(
            {Agent.status: AgentStatus.IDLE}, synchronize_session=False
        )

    # Remove workspace directory
    if project.workspace_path and os.path.isdir(project.workspace_path):
        def _on_rm_error(func, path, exc_info):
            """Handle read-only files on Windows — clear flag and retry."""
            import stat
            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(project.workspace_path, onerror=_on_rm_error)

    db.delete(project)
    db.commit()

    # Notify clients: stuck agents have been reset
    if stuck_agent_ids:
        from app.api.ws import broadcast_sync
        for agent_id in stuck_agent_ids:
            broadcast_sync("agent_update", {"id": agent_id, "status": "idle"})

    _broadcast_project_update("deleted", project_id)

    return {"message": f"项目「{project.name}」已删除"}


# ── Join requests ────────────────────────────────────────────────────

class JoinApplyRequest(BaseModel):
    project_id: str = Field(..., description="项目规范 ID，如 PROJ-20260716-abc123")


class JoinRequestResponse(BaseModel):
    id: int
    project_id: int
    user_id: int
    username: str
    status: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True


@router.post("/join", status_code=status.HTTP_201_CREATED)
def apply_join_project(
    req: JoinApplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Apply to join a project by canonical project_id."""
    project = db.query(Project).filter(Project.project_id == req.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"项目 {req.project_id} 不存在")

    # Already a member?
    if project.owner_id == user.id:
        raise HTTPException(status_code=409, detail="你已经是该项目的负责人")
    existing_member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == user.id,
    ).first()
    if existing_member:
        raise HTTPException(status_code=409, detail="你已经是该项目的成员")

    # Already applied?
    existing_req = db.query(JoinRequest).filter(
        JoinRequest.project_id == project.id,
        JoinRequest.user_id == user.id,
        JoinRequest.status == JoinStatus.PENDING,
    ).first()
    if existing_req:
        raise HTTPException(status_code=409, detail="你已经申请过加入该项目，请等待审批")

    join_req = JoinRequest(
        project_id=project.id,
        user_id=user.id,
        username=user.username,
        status=JoinStatus.PENDING,
    )
    db.add(join_req)
    db.commit()
    db.refresh(join_req)

    return {"message": f"已申请加入项目「{project.name}」，请等待项目负责人审批", "request_id": join_req.id}


@router.get("/{project_id}/applications", response_model=list[JoinRequestResponse])
def list_applications(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List pending join requests. Only owner/admin can view."""
    project = _require_membership(project_id, user, db)
    if project.owner_id != user.id:
        membership = db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ).first()
        if not membership or membership.role not in (ProjectRole.OWNER, ProjectRole.ADMIN):
            raise HTTPException(status_code=403, detail="只有项目主管或管理员才能查看申请列表")

    requests = db.query(JoinRequest).filter(
        JoinRequest.project_id == project_id,
        JoinRequest.status == JoinStatus.PENDING,
    ).order_by(JoinRequest.created_at.desc()).all()

    return [JoinRequestResponse.model_validate(r) for r in requests]


@router.post("/{project_id}/applications/{app_id}/approve")
def approve_application(
    project_id: int,
    app_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve a join request. Only owner/admin can approve."""
    project = _require_membership(project_id, user, db)
    if project.owner_id != user.id:
        membership = db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ).first()
        if not membership or membership.role not in (ProjectRole.OWNER, ProjectRole.ADMIN):
            raise HTTPException(status_code=403, detail="只有项目主管或管理员才能审批申请")

    join_req = db.query(JoinRequest).filter(
        JoinRequest.id == app_id,
        JoinRequest.project_id == project_id,
    ).first()
    if not join_req:
        raise HTTPException(status_code=404, detail="申请记录不存在")
    if join_req.status != JoinStatus.PENDING:
        raise HTTPException(status_code=400, detail="该申请已被处理")

    join_req.status = JoinStatus.APPROVED
    join_req.reviewed_at = datetime.now(timezone.utc)

    # Add as member
    db.add(ProjectMember(project_id=project_id, user_id=join_req.user_id, role=ProjectRole.MEMBER))
    db.commit()

    return {"message": f"已通过 {join_req.username} 的加入申请"}


@router.post("/{project_id}/applications/{app_id}/reject")
def reject_application(
    project_id: int,
    app_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject a join request. Only owner/admin can reject."""
    project = _require_membership(project_id, user, db)
    if project.owner_id != user.id:
        membership = db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ).first()
        if not membership or membership.role not in (ProjectRole.OWNER, ProjectRole.ADMIN):
            raise HTTPException(status_code=403, detail="只有项目主管或管理员才能审批申请")

    join_req = db.query(JoinRequest).filter(
        JoinRequest.id == app_id,
        JoinRequest.project_id == project_id,
    ).first()
    if not join_req:
        raise HTTPException(status_code=404, detail="申请记录不存在")
    if join_req.status != JoinStatus.PENDING:
        raise HTTPException(status_code=400, detail="该申请已被处理")

    join_req.status = JoinStatus.REJECTED
    join_req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": f"已驳回 {join_req.username} 的加入申请"}
