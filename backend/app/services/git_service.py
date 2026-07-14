import os
from pathlib import Path
from typing import Any

from git import Repo, GitCommandError


# ── Helpers ───────────────────────────────────────────────────────────

def _verify_safe_path(workspace: str, target: str) -> str:
    """Resolve and verify the target path is inside workspace."""
    full = os.path.realpath(os.path.join(workspace, target))
    ws = os.path.realpath(workspace)
    if not full.startswith(ws):
        raise ValueError(f"Path escapes workspace: {target}")
    return full


# ── Git operations ────────────────────────────────────────────────────

def init_repo(path: str) -> Repo:
    """Initialize a git repository at path."""
    os.makedirs(path, exist_ok=True)
    try:
        return Repo(path)
    except GitCommandError:
        return Repo.init(path)


def get_repo(workspace: str) -> Repo | None:
    """Get Repo object, or None if not found."""
    try:
        return Repo(workspace)
    except GitCommandError:
        return None


def commit(workspace: str, message: str) -> str | None:
    """Stage all, commit, return commit hash. None if nothing to commit."""
    repo = get_repo(workspace)
    if not repo:
        return None
    repo.git.add(A=True)
    if not repo.is_dirty(index=True, working_tree=False, untracked_files=True):
        return None
    c = repo.index.commit(message)
    return c.hexsha


def get_diff(workspace: str) -> str:
    """Return git diff of unstaged + staged changes."""
    repo = get_repo(workspace)
    if not repo:
        return ""
    try:
        staged = repo.git.diff("--cached")
    except GitCommandError:
        staged = ""
    try:
        unstaged = repo.git.diff()
    except GitCommandError:
        unstaged = ""
    if staged and unstaged:
        return staged + "\n" + unstaged
    return staged or unstaged or ""


def commit_history(workspace: str, max_count: int = 50) -> list[dict[str, Any]]:
    """Return list of recent commits."""
    repo = get_repo(workspace)
    if not repo:
        return []
    commits = []
    for c in repo.iter_commits(max_count=max_count):
        commits.append({
            "hash": c.hexsha,
            "message": c.message.strip(),
            "author": str(c.author),
            "date": c.committed_datetime.isoformat(),
        })
    return commits


def rollback(workspace: str, commit_hash: str) -> bool:
    """Reset --hard to a commit. Returns True on success."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        repo.git.reset("--hard", commit_hash)
        return True
    except GitCommandError:
        return False


# ── File operations ───────────────────────────────────────────────────

_EXCLUDED = {".git", "__pycache__", "node_modules", ".venv", "dist"}


def list_files(workspace: str, subpath: str = "") -> list[dict[str, Any]]:
    """Recursively list files in workspace. Returns tree nodes."""
    target = _verify_safe_path(workspace, subpath or ".")
    nodes: list[dict] = []

    try:
        entries = sorted(os.listdir(target), key=lambda x: (os.path.isdir(os.path.join(target, x)), x))
    except (FileNotFoundError, NotADirectoryError):
        return nodes

    for name in entries:
        if name in _EXCLUDED:
            continue
        full = os.path.join(target, name)
        rel = os.path.relpath(full, workspace).replace("\\", "/")
        if subpath:
            rel = f"{subpath}/{name}"
        is_dir = os.path.isdir(full)
        node: dict = {
            "name": name,
            "path": rel,
            "type": "dir" if is_dir else "file",
        }
        if is_dir:
            node["children"] = list_files(workspace, rel)
        else:
            node["size"] = os.path.getsize(full)
        nodes.append(node)

    return nodes


def read_file(workspace: str, filepath: str, max_size: int = 256 * 1024) -> str:
    """Read a file's content. Limits to max_size bytes."""
    target = _verify_safe_path(workspace, filepath)
    size = os.path.getsize(target)
    if size > max_size * 2:
        return f"// File too large ({size} bytes, max {max_size * 2})"
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        return f.read(max_size)


def write_file(workspace: str, filepath: str, content: str) -> str:
    """Write content to a file, creating parent dirs as needed."""
    target = _verify_safe_path(workspace, filepath)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return target


def create_folder(workspace: str, folder_path: str) -> str:
    """Create a folder inside workspace."""
    target = _verify_safe_path(workspace, folder_path)
    os.makedirs(target, exist_ok=True)
    return target


def upload_file(workspace: str, filepath: str, content: bytes) -> str:
    """Write binary content to a file."""
    target = _verify_safe_path(workspace, filepath)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(content)
    return target
