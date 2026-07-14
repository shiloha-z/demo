import os
from pathlib import Path
from typing import Any

from git import Repo, GitCommandError, InvalidGitRepositoryError


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
    """Initialize a git repository at path with an initial commit on master."""
    os.makedirs(path, exist_ok=True)
    try:
        return Repo(path)
    except (GitCommandError, InvalidGitRepositoryError):
        repo = Repo.init(path)
        # Create an initial commit so master branch exists
        readme = os.path.join(path, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write("# Project Workspace\n")
        repo.git.add(A=True)
        try:
            repo.index.commit("Initial commit")
            # Explicitly create master branch pointing to this commit
            repo.git.branch("-M", "master")
        except Exception:
            pass  # may fail if git config missing; acceptable
        return repo


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


# ── Branch operations (for per-task isolation) ────────────────────────

def create_branch(workspace: str, branch_name: str) -> bool:
    """Create and switch to a new branch from master. Creates master if needed."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        # Delete stale branch with same name if exists
        try:
            repo.git.branch("-D", branch_name)
        except GitCommandError:
            pass
        # Find or create the base branch (master/main)
        base = None
        for candidate in ["master", "main"]:
            try:
                repo.git.rev_parse(candidate)
                base = candidate
                break
            except GitCommandError:
                continue
        if base:
            repo.git.checkout("-f", base)
        else:
            # No base branch exists — rename current branch to master
            try:
                repo.git.branch("-M", "master")
                base = "master"
            except GitCommandError:
                pass
        repo.git.checkout("-b", branch_name)
        return True
    except GitCommandError:
        return False


def switch_branch(workspace: str, branch_name: str) -> bool:
    """Switch to an existing branch (force — discards uncommitted changes)."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        repo.git.checkout("-f", branch_name)
        return True
    except GitCommandError:
        return False


def merge_branch(workspace: str, source_branch: str, target_branch: str = "master") -> bool:
    """Merge source_branch into target_branch. Force-switches to target first."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        # Switch to target (force — discard any uncommitted changes on current branch)
        try:
            repo.git.checkout("-f", target_branch)
        except GitCommandError:
            try:
                repo.git.checkout("-f", "main")
                target_branch = "main"
            except GitCommandError:
                return False
        # Merge
        repo.git.merge(source_branch)
        return True
    except GitCommandError:
        # Abort merge on conflict
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass
        return False


def delete_branch(workspace: str, branch_name: str) -> bool:
    """Force-delete a branch."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        repo.git.branch("-D", branch_name)
        return True
    except GitCommandError:
        return False


def diff_vs_master(workspace: str) -> str:
    """Get diff of all changes on current branch vs master.

    Stages everything, then diffs against the base branch.
    This captures all work the agent did on its task branch,
    including new (untracked) files.
    """
    repo = get_repo(workspace)
    if not repo:
        return ""
    # Find the base branch
    base = "master"
    try:
        repo.git.rev_parse("master")
    except GitCommandError:
        try:
            repo.git.rev_parse("main")
            base = "main"
        except GitCommandError:
            return get_diff(workspace)
    try:
        # Stage everything first so new files show up in diff
        repo.git.add(A=True)
        return repo.git.diff("--cached", base)
    except GitCommandError:
        return get_diff(workspace)


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
