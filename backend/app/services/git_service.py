import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any

from git import Repo, GitCommandError, InvalidGitRepositoryError


_WORKSPACE_LOCKS: dict[str, RLock] = {}
_WORKSPACE_LOCKS_GUARD = RLock()


@contextmanager
def workspace_lock(workspace: str):
    """Serialize all Git and filesystem operations for one workspace."""
    key = os.path.normcase(os.path.realpath(workspace))
    with _WORKSPACE_LOCKS_GUARD:
        lock = _WORKSPACE_LOCKS.setdefault(key, RLock())
    with lock:
        yield


def _workspace_locked(func):
    @wraps(func)
    def wrapped(workspace: str, *args, **kwargs):
        with workspace_lock(workspace):
            return func(workspace, *args, **kwargs)
    return wrapped


# ── Helpers ───────────────────────────────────────────────────────────

def _verify_safe_path(workspace: str, target: str) -> str:
    """Resolve and verify the target path is inside workspace."""
    full = os.path.realpath(os.path.join(workspace, target))
    ws = os.path.realpath(workspace)
    try:
        is_inside_workspace = os.path.commonpath([ws, full]) == ws
    except ValueError:
        is_inside_workspace = False
    if not is_inside_workspace:
        raise ValueError(f"Path escapes workspace: {target}")
    return full


# ── Git operations ────────────────────────────────────────────────────

def init_repo(path: str) -> Repo:
    """Initialize a git repository at path with an initial commit on master.

    Idempotent: if the repo already exists (e.g. a prior empty `Repo.init`
    with no commit), this still ensures a `master` branch exists with an
    initial commit, instead of silently returning an empty repo.
    """
    os.makedirs(path, exist_ok=True)
    repo = Repo.init(path)
    # Ensure master branch exists with at least one commit.
    try:
        repo.git.rev_parse("master")
    except GitCommandError:
        readme = os.path.join(path, "README.md")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write("# Project Workspace\n")
        repo.git.add(A=True)
        try:
            repo.index.commit("Initial commit")
        except Exception:
            pass  # nothing to commit; acceptable
        try:
            repo.git.branch("-M", "master")
        except GitCommandError:
            pass
    return repo


def get_repo(workspace: str) -> Repo | None:
    """Get Repo object, or None if not found."""
    try:
        return Repo(workspace)
    except GitCommandError:
        return None


@_workspace_locked
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


@_workspace_locked
def commit_allow_empty(workspace: str, message: str) -> str | None:
    """Create an empty commit (used as an auditable marker, e.g. an approval).

    Unlike `commit()`, this always succeeds even when there are no file
    changes, so callers can guarantee a new commit hash is produced.
    Returns the new commit hash, or None on failure.
    """
    repo = get_repo(workspace)
    if not repo:
        return None
    try:
        repo.git.commit("--allow-empty", "-m", message)
        return repo.head.commit.hexsha
    except GitCommandError:
        return None


@_workspace_locked
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


@_workspace_locked
def rollback(workspace: str, commit_hash: str, message: str | None = None) -> str | None:
    """Revert the workspace to a past commit in an *auditable* way.

    Strategy:
      1. Make sure we are on the base branch (master/main) — the file tree
         and version list are read from there.
      2. Use ``git revert --no-commit <commit>..HEAD`` to undo every commit
         made AFTER the target, then create ONE new commit capturing the
         target state. This keeps history linear and fully auditable: you can
         see exactly when and to which version a rollback happened.

    Falls back to a plain ``reset --hard`` if revert is not applicable
    (e.g. target is HEAD, or a conflict during revert).

    Returns the new commit hash, or None on failure.
    """
    repo = get_repo(workspace)
    if not repo:
        return None

    # 1. Ensure we are on the base branch (file tree reads from here).
    try:
        base = _get_base_branch(repo)
    except Exception:
        base = "master"
    try:
        repo.git.checkout("-f", base)
    except GitCommandError:
        pass

    # 2. Revert every commit after the target.
    try:
        repo.git.revert("--no-commit", f"{commit_hash}..HEAD")
    except GitCommandError:
        # Nothing to revert (target == HEAD) or conflict → fall back.
        try:
            repo.git.revert("--abort")
        except GitCommandError:
            pass
        try:
            repo.git.reset("--hard", commit_hash)
            return commit_hash
        except GitCommandError:
            return None

    # Revert produced no staged changes (e.g. target was HEAD) → no-op.
    if not repo.index.diff("HEAD"):
        try:
            repo.git.revert("--abort")
        except GitCommandError:
            pass
        return commit_hash

    msg = message or f"Revert to {commit_hash[:7]}"
    try:
        c = repo.index.commit(msg)
        return c.hexsha
    except Exception:
        # Commit failed though changes were staged — restore state.
        try:
            repo.git.revert("--abort")
        except GitCommandError:
            pass
        try:
            repo.git.reset("--hard", base)
        except GitCommandError:
            pass
        return None


# ── Branch operations (for per-task isolation) ────────────────────────

@_workspace_locked
def branch_exists(workspace: str, branch_name: str) -> bool:
    """Check whether a Git branch exists in the workspace."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        repo.git.rev_parse("--verify", branch_name)
        return True
    except GitCommandError:
        return False


@_workspace_locked
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


@_workspace_locked
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


@_workspace_locked
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


@_workspace_locked
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


@_workspace_locked
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


# ── File operations (always read from master branch) ───────────────────

_EXCLUDED = {".git", "__pycache__", "node_modules", ".venv", "dist"}

# Cache the base branch name per repo (it doesn't change during a session)
_BASE_BRANCH: dict[str, str] = {}


def _get_base_branch(repo: Repo) -> str:
    """Resolve the base branch name (master or main). Cache per repo."""
    path = repo.working_dir
    if path not in _BASE_BRANCH:
        for candidate in ["master", "main"]:
            try:
                repo.git.rev_parse(candidate)
                _BASE_BRANCH[path] = candidate
                break
            except GitCommandError:
                continue
        else:
            _BASE_BRANCH[path] = "master"
    return _BASE_BRANCH[path]


@_workspace_locked
def list_files(workspace: str, subpath: str = "", ref: str = "") -> list[dict[str, Any]]:
    """List files from the project workspace.

    If `ref` is given (e.g. "master"), lists from that git branch snapshot.
    If `ref` is None (default), lists from the filesystem working tree.

    The file manager UI passes ref="master" to show the approved project state;
    agent tools pass ref=None to see the current working tree.
    """
    if ref:
        repo = get_repo(workspace)
        if repo:
            try:
                return _list_from_git(repo, ref, subpath)
            except Exception:
                pass
        return []

    # Filesystem listing
    target_dir = _verify_safe_path(workspace, subpath)
    if os.path.isdir(target_dir):
        return _list_from_fs(workspace, subpath)

    # Fallback to git if filesystem path doesn't exist yet
    repo = get_repo(workspace)
    if repo:
        try:
            base = _get_base_branch(repo)
            return _list_from_git(repo, base, subpath)
        except Exception:
            pass

    return []


def _list_from_git(repo: Repo, base: str, subpath: str) -> list[dict[str, Any]]:
    """List files using git ls-tree from a specific branch."""
    nodes: list[dict] = []
    prefix = f"{subpath}/" if subpath else ""

    try:
        tree_ref = f"{base}:{subpath}" if subpath else base
        output = repo.git.ls_tree(tree_ref)
    except GitCommandError:
        # Branch does not exist / no commits yet. Signal the caller to
        # fall back to the real filesystem instead of returning empty.
        raise

    for line in output.strip().split("\n"):
        if not line:
            continue
        # Format: "<mode> <type> <hash>\t<name>"
        parts = line.split()
        if len(parts) < 4:
            continue
        entry_type = parts[1]  # "tree" or "blob"
        name = line.split("\t", 1)[1] if "\t" in line else parts[3]
        if name in _EXCLUDED:
            continue

        path = f"{prefix}{name}"
        node: dict = {
            "name": name,
            "path": path,
            "type": "dir" if entry_type == "tree" else "file",
        }
        if entry_type == "tree":
            node["children"] = _list_from_git(repo, base, path)
        nodes.append(node)

    return nodes


def _list_from_fs(workspace: str, subpath: str) -> list[dict[str, Any]]:
    """Filesystem-based file listing (fallback)."""
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
            node["children"] = _list_from_fs(workspace, rel)
        else:
            node["size"] = os.path.getsize(full)
        nodes.append(node)

    return nodes


@_workspace_locked
def read_file(workspace: str, filepath: str, max_size: int = 256 * 1024, ref: str = "") -> str:
    """Read file content from the project workspace.

    If `ref` is given (e.g. "master"), reads from that git branch snapshot.
    If `ref` is "" (default), reads from the filesystem working tree.

    The file manager UI passes ref="master" to show the approved project state;
    agent tools pass no ref to read the current working tree.
    """
    if ref:
        repo = get_repo(workspace)
        if repo:
            try:
                content = repo.git.show(f"{ref}:{filepath}")
                if len(content) > max_size * 2:
                    return f"// File too large ({len(content)} chars, max {max_size * 2})"
                return content[:max_size]
            except GitCommandError:
                raise FileNotFoundError(f"File not found in {ref}: {filepath}")
        raise FileNotFoundError(f"File not found: {filepath}")

    # Filesystem read — always reflects current working-tree state
    target = _verify_safe_path(workspace, filepath)
    if not os.path.isfile(target):
        raise FileNotFoundError(f"File not found: {filepath}")
    size = os.path.getsize(target)
    if size > max_size * 2:
        return f"// File too large ({size} bytes, max {max_size * 2})"
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        return f.read(max_size)


@_workspace_locked
def write_file(workspace: str, filepath: str, content: str) -> str:
    """Write content to a file, creating parent dirs as needed."""
    target = _verify_safe_path(workspace, filepath)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return target


@_workspace_locked
def create_folder(workspace: str, folder_path: str) -> str:
    """Create a folder inside workspace. Adds .gitkeep so git tracks it."""
    target = _verify_safe_path(workspace, folder_path)
    os.makedirs(target, exist_ok=True)
    # Git doesn't track empty directories — add .gitkeep placeholder
    gitkeep = os.path.join(target, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w", encoding="utf-8") as f:
            f.write("")
    return target


@_workspace_locked
def delete_path(workspace: str, target_path: str) -> str:
    """Delete a file or folder inside workspace. Returns the deleted path."""
    import shutil

    target = _verify_safe_path(workspace, target_path)

    if not os.path.exists(target):
        raise FileNotFoundError(f"Path not found: {target_path}")

    if os.path.isfile(target):
        os.remove(target)
    elif os.path.isdir(target):
        shutil.rmtree(target)
    else:
        raise ValueError(f"Unsupported path type: {target_path}")

    return target


@_workspace_locked
def upload_file(workspace: str, filepath: str, content: bytes) -> str:
    """Write binary content to a file."""
    target = _verify_safe_path(workspace, filepath)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(content)
    return target
