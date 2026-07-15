import os, re, shutil
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from typing import List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc

from app.core.database import get_db
from app.core.config import settings
from app.core.auth import get_current_user
from app.models.models import User, Project, Task, Review, Version, Agent, AgentStatus
from app.services import git_service as git

router = APIRouter(prefix="/api/projects", tags=["Projects"])


# ── Schemas ───────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    workspace_name: str = Field(default="", max_length=100, description="工作空间文件夹名，留空则使用项目名")


class ProjectResponse(BaseModel):
    id: int
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


def _get_workspace(project_id: int, user: User, db: Session) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.workspace_path:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    return project.workspace_path


# ── Project CRUD ──────────────────────────────────────────────────────

@router.get("", response_model=ProjectListResponse)
def list_projects(
    sort: str = Query(default="created_desc", description="created_desc | created_asc | updated_desc | name_asc | name_desc"),
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
    projects = db.query(Project).options(joinedload(Project.owner)).order_by(order).all()
    return ProjectListResponse(projects=[ProjectResponse.model_validate(p) for p in projects])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(req: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = Project(name=req.name, description=req.description, owner_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)

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
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        owner_id=project.owner_id,
        owner_name=project.owner.username if project.owner else "",
        workspace_path=project.workspace_path or "",
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


# ── File management (MUST be before /{project_id}) ────────────────────

@router.get("/{project_id}/files")
def file_tree(
    project_id: int,
    path: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = _get_workspace(project_id, user, db)
    try:
        nodes = git.list_files(workspace, path)
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
    workspace = _get_workspace(project_id, user, db)
    try:
        content = git.read_file(workspace, path)
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
        if use_per_file_paths:
            target_path = file_paths[i]
        else:
            dir_part = path if path else ""
            filename = file.filename or "untitled"
            target_path = f"{dir_part}/{filename}".lstrip("/") if dir_part else filename

        # Sanitize
        full_path = os.path.normpath(os.path.join(workspace, target_path))
        if not full_path.startswith(os.path.normpath(workspace) + os.sep) and full_path != os.path.normpath(workspace):
            raise HTTPException(status_code=400, detail=f"Invalid path: {target_path}")

        content = await file.read()
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(content)
        else:
            git.write_file(workspace, target_path, decoded)

        uploaded.append({"path": target_path, "filename": target_path.split("/")[-1]})

    _touch_project(db, project_id)
    git.commit(workspace, f"Upload {len(uploaded)} file(s)")
    return {"files": uploaded, "message": f"{len(uploaded)} file(s) uploaded"}


# ── Project detail + delete ─────────────────────────────────────────

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.query(Project).options(joinedload(Project.owner)).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a project. Only the owner can delete it."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有项目创建者才能删除项目")

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
        shutil.rmtree(project.workspace_path, ignore_errors=True)

    db.delete(project)
    db.commit()

    # Notify clients: stuck agents have been reset
    if stuck_agent_ids:
        from app.api.ws import broadcast_sync
        for agent_id in stuck_agent_ids:
            broadcast_sync("agent_update", {"id": agent_id, "status": "idle"})

    return {"message": f"项目「{project.name}」已删除"}
