import os
import subprocess
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any

from git import Repo, GitCommandError, InvalidGitRepositoryError, NoSuchPathError


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
    """Get Repo object, or None if not found / not a valid, usable repository.

    Catches InvalidGitRepositoryError too, so an "orphaned" worktree (working
    directory present but its gitdir pruned) is treated as missing rather than
    raising and crashing the caller.  We also run a real Git command because
    GitPython constructs a Repo object for an orphaned worktree without error,
    yet every actual command then fails with "not a git repository".
    """
    try:
        repo = Repo(workspace)
        repo.git.rev_parse("--is-inside-work-tree")
        return repo
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError):
        return None


def get_base_branch(workspace: str) -> str:
    """Return the repository's stable integration branch."""
    repo = get_repo(workspace)
    if not repo:
        return "master"
    return _get_base_branch(repo)


@_workspace_locked
def head_commit(workspace: str, ref: str = "HEAD") -> str:
    repo = get_repo(workspace)
    if not repo:
        return ""
    try:
        return repo.git.rev_parse(ref).strip()
    except GitCommandError:
        return ""


def default_task_worktree_path(workspace: str, task_id: int) -> str:
    """Keep task worktrees beside, never inside, the project worktree."""
    root = Path(workspace).resolve()
    return str(root.parent / f"{root.name}.worktrees" / f"task-{task_id}")


def _is_managed_worktree(base_workspace: str, worktree_path: str) -> bool:
    base = Path(base_workspace).resolve()
    candidate = Path(worktree_path).resolve()
    managed_root = base.parent / f"{base.name}.worktrees"
    try:
        return candidate.is_relative_to(managed_root) and candidate.name.startswith("task-")
    except AttributeError:  # Python < 3.9 compatibility
        return str(candidate).startswith(str(managed_root)) and candidate.name.startswith("task-")


def create_task_worktree(base_workspace: str, worktree_path: str, branch_name: str) -> tuple[bool, str]:
    """Create an isolated task worktree from the current base branch.

    Git's common metadata is shared by all worktrees, so only creation is
    locked on the project workspace.  Subsequent agent file operations lock
    the task worktree independently and can run in parallel.
    """
    if not _is_managed_worktree(base_workspace, worktree_path):
        return False, "Unsafe task worktree path"
    with workspace_lock(base_workspace):
        repo = get_repo(base_workspace)
        if not repo:
            return False, "Project repository not found"
        path = Path(worktree_path)
        if path.exists():
            existing = get_repo(str(path))
            if existing:
                return True, ""
            return False, "Task worktree path already exists and is not a Git worktree"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            base_branch = _get_base_branch(repo)
            try:
                repo.git.rev_parse("--verify", branch_name)
                repo.git.worktree("add", str(path), branch_name)
            except GitCommandError:
                repo.git.worktree("add", "-b", branch_name, str(path), base_branch)
            return True, ""
        except GitCommandError as exc:
            return False, str(exc)


def ensure_worktree(base_workspace: str, worktree_path: str, branch_name: str) -> tuple[bool, str]:
    """Ensure *worktree_path* is a usable Git worktree for *branch_name*.

    Unlike ``create_task_worktree`` this also *repairs* worktrees whose Git
    metadata (gitdir) was pruned/removed while the working directory is still
    present on disk -- an "orphaned" worktree.  Repairing preserves any files
    already written into the worktree so no agent work is lost.

    Returns ``(ok, error)``.
    """
    import shutil

    path = Path(worktree_path)
    # Already a valid, registered worktree -> nothing to do.
    if path.exists() and get_repo(str(path)):
        return True, ""
    if not path.exists():
        return create_task_worktree(base_workspace, worktree_path, branch_name)

    # Orphaned worktree: working dir present but gitdir pruned.  Back up the
    # working files, recreate the worktree cleanly, then restore the files.
    backup = path.parent / (path.name + ".repair.bak")
    if backup.exists():
        shutil.rmtree(str(backup), ignore_errors=True)
    try:
        shutil.move(str(path), str(backup))
    except OSError as exc:
        return False, f"无法备份损坏的工作树：{exc}"
    ok, err = create_task_worktree(base_workspace, worktree_path, branch_name)
    if not ok:
        # Restore the backup so agent work is not lost.
        if not path.exists():
            try:
                shutil.move(str(backup), str(path))
            except OSError:
                pass
        return False, err
    # Restore working files (skip the freshly-created .git link).
    for entry in os.listdir(str(backup)):
        if entry == ".git":
            continue
        src = os.path.join(str(backup), entry)
        dst = os.path.join(str(path), entry)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError:
            pass
    shutil.rmtree(str(backup), ignore_errors=True)
    return True, ""


def remove_task_worktree(base_workspace: str, worktree_path: str) -> bool:
    """Remove only a managed, no-longer-running task worktree."""
    if not worktree_path or not _is_managed_worktree(base_workspace, worktree_path):
        return False
    with workspace_lock(base_workspace):
        repo = get_repo(base_workspace)
        if not repo:
            return False
        try:
            repo.git.worktree("remove", "--force", worktree_path)
            parent = Path(worktree_path).parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            return True
        except GitCommandError:
            return False


def cleanup_task_resources(project_workspace: str, task_worktree: str, branch_name: str) -> None:
    """Remove task worktree and branch — safe to call even if already cleaned up."""
    if task_worktree:
        remove_task_worktree(project_workspace, task_worktree)
    if branch_name:
        delete_branch(project_workspace, branch_name)


def sync_task_branch_with_master(task_workspace: str, branch_name: str) -> tuple[bool, list[str]]:
    """Merge latest master into the task branch in *task_workspace*.

    Returns ``(clean, conflict_files)``.  Call this before integration so the
    task branch is always up-to-date with master, avoiding the "perpetual
    conflict" loop when multiple tasks touch the same files.
    """
    repo = get_repo(task_workspace)
    if not repo:
        return False, []
    base = _get_base_branch(repo)
    try:
        repo.git.checkout(branch_name)
        repo.git.merge(base)
        return True, []
    except GitCommandError:
        try:
            conflicts = repo.git.diff("--name-only", "--diff-filter=U").splitlines()
        except GitCommandError:
            conflicts = []
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass
        if conflicts:
            return False, [f for f in conflicts if f]
        return False, []


def begin_integration(workspace: str, source_branch: str) -> dict[str, Any]:
    """Start a no-commit merge in the base workspace.

    The caller owns the project merge lock while it validates and either
    commits or aborts this integration attempt.
    """
    repo = get_repo(workspace)
    if not repo:
        return {"status": "error", "error": "Project repository not found"}
    try:
        base_branch = _get_base_branch(repo)
        repo.git.checkout(base_branch)
        if repo.is_dirty(untracked_files=True):
            return {"status": "error", "error": "Base workspace has uncommitted changes"}
        repo.git.merge("--no-commit", "--no-ff", source_branch)
        return {"status": "ready", "base_branch": base_branch}
    except GitCommandError as exc:
        try:
            conflicts = repo.git.diff("--name-only", "--diff-filter=U").splitlines()
        except GitCommandError:
            conflicts = []
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass
        if conflicts:
            return {"status": "conflict", "files": conflicts}
        return {"status": "error", "error": str(exc)}


def finish_integration(workspace: str, message: str) -> tuple[bool, str]:
    repo = get_repo(workspace)
    if not repo:
        return False, "Project repository not found"
    try:
        commit_hash = repo.index.commit(message).hexsha
        return True, commit_hash
    except Exception as exc:
        return False, str(exc)


def abort_integration(workspace: str) -> None:
    repo = get_repo(workspace)
    if not repo:
        return
    try:
        repo.git.merge("--abort")
    except GitCommandError:
        pass


def run_integration_checks(workspace: str, command: str, timeout_seconds: int) -> tuple[bool, str]:
    """Run mandatory whitespace validation and an optional project test command."""
    repo = get_repo(workspace)
    if not repo:
        return False, "Project repository not found"
    try:
        repo.git.diff("--check", "--cached")
    except GitCommandError as exc:
        return False, f"Git diff check failed: {exc}"
    if not command.strip():
        return True, "Git diff check passed (no MERGE_TEST_COMMAND configured)"
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        return False, f"Test command timed out after {timeout_seconds}s"
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode:
        return False, f"Test command failed (exit {completed.returncode}): {output[-2000:]}"
    return True, output[-2000:] or "Test command passed"


def prepare_conflict_resolution(task_workspace: str, base_workspace: str, branch_name: str) -> tuple[bool, list[str], str]:
    """Merge the latest base branch into a task worktree and keep conflict markers.

    A resolver agent can then edit the conflicting files.  A later normal
    task commit completes this merge and starts a fresh human review round.
    """
    with workspace_lock(task_workspace):
        repo = get_repo(task_workspace)
        base_repo = get_repo(base_workspace)
        if not repo or not base_repo:
            return False, [], "Task or project repository not found"
        try:
            base_branch = _get_base_branch(base_repo)
            repo.git.checkout(branch_name)
            repo.git.merge(base_branch)
            # The branch was updated cleanly while the integration worker was
            # waiting.  It is safe to try integration again instead of using
            # a resolver agent.
            return True, [], ""
        except GitCommandError as exc:
            try:
                files = repo.git.diff("--name-only", "--diff-filter=U").splitlines()
            except GitCommandError:
                files = []
            if files:
                return True, files, ""
            return False, [], str(exc)


_GENERATED_ARTIFACT_PARTS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "dist", "build", "coverage",
}
_GENERATED_ARTIFACT_NAMES = {".coverage"}


def _stage_agent_changes(repo: Repo) -> None:
    """Stage workspace changes while keeping test/build artifacts out of commits.

    Also unstages files whose only change is a mode/permission toggle (the diff
    shows +0 / −0), so the review diff only surfaces meaningful content changes.
    """
    repo.git.add(A=True)
    staged = repo.git.diff("--cached", "--name-only").splitlines()
    # Unstage generated artifacts.
    generated = [
        path for path in staged
        if Path(path).name in _GENERATED_ARTIFACT_NAMES
        or any(part in _GENERATED_ARTIFACT_PARTS for part in Path(path).parts)
        or Path(path).suffix in {".pyc", ".pyo"}
    ]
    if generated:
        repo.git.reset("--", *generated)
    # Unstage mode-only changes (files showing +0 / −0).
    try:
        numstat = repo.git.diff("--cached", "--numstat").splitlines()
        empty = [line.split("\t")[2] for line in numstat
                 if line.startswith("0\t0\t")]
        if empty:
            repo.git.reset("--", *empty)
    except GitCommandError:
        pass


@_workspace_locked
def commit(workspace: str, message: str) -> str | None:
    """Stage all, commit, return commit hash. None if nothing to commit."""
    repo = get_repo(workspace)
    if not repo:
        return None
    _stage_agent_changes(repo)
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
    base = _get_base_branch(repo)
    try:
        # Stage agent-authored changes first so new files show up in diff.
        # Test/build artifacts are deliberately kept out of the review.
        _stage_agent_changes(repo)
        return repo.git.diff("--cached", base)
    except GitCommandError:
        return get_diff(workspace)


def repo_has_uncommitted_changes(workspace: str) -> bool:
    """Return True if the working directory has uncommitted changes."""
    repo = get_repo(workspace)
    if not repo:
        return False
    try:
        return repo.is_dirty(index=True, working_tree=True, untracked_files=True)
    except Exception:
        return False


def suspicious_files_in_diff(workspace: str, commit_hash: str) -> list[str]:
    """Return files whose committed diff looks like a placeholder / incomplete write.

    Detects the "disk hallucination" pattern where the agent claims to have
    written a rich file but the actual content is just a stub header.
    """
    repo = get_repo(workspace)
    if not repo:
        return []
    base = _get_base_branch(repo)
    try:
        numstat = repo.git.diff(base, commit_hash, "--numstat").splitlines()
    except GitCommandError:
        return []
    suspicious: list[str] = []
    for line in numstat:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_str, _, filename = parts
        try:
            added = int(added_str)
        except ValueError:
            continue
        # A file with exactly 1 added line is almost certainly a placeholder
        # (e.g. "# Project Workspace"). Flag it so the runner can warn.
        if added <= 1:
            suspicious.append(filename)
    return suspicious


@_workspace_locked
def diff_commit_vs_base(workspace: str, commit_hash: str) -> str:
    """Diff a specific commit against the base branch.

    Unlike ``diff_vs_master`` (which re-stages the live working directory),
    this always diffs the *committed* snapshot so the review shows exactly
    what was committed, even if the worktree was later mutated by conflict
    resolution or a re-run.
    """
    repo = get_repo(workspace)
    if not repo:
        return ""
    base = _get_base_branch(repo)
    try:
        return repo.git.diff(base, commit_hash)
    except GitCommandError:
        return ""


@_workspace_locked
def changed_files_vs_base(workspace: str, ref: str = "") -> set[str]:
    """Return files changed from the base branch, including untracked files."""
    repo = get_repo(workspace)
    if not repo:
        return set()
    try:
        base = _get_base_branch(repo)
        args = ["--name-only", base]
        if ref:
            args.append(ref)
        changed = set(filter(None, repo.git.diff(*args).splitlines()))
    except GitCommandError:
        changed = set()
    if not ref:
        changed.update(path.replace("\\", "/") for path in repo.untracked_files)
    return changed


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


def list_files_snapshot(workspace: str, ref: str, subpath: str = "") -> list[dict[str, Any]]:
    """Read a committed Git snapshot without taking the mutable workspace lock.

    `git ls-tree` only reads immutable objects addressed by ``ref``. Task
    workspace previews use this path so they remain responsive while an agent
    owns the working tree lock to write files or switch branches.
    """
    repo = get_repo(workspace)
    if not repo:
        return []
    try:
        return _list_from_git(repo, ref, subpath)
    except (GitCommandError, OSError, ValueError):
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


def read_file_snapshot(workspace: str, ref: str, filepath: str, max_size: int = 256 * 1024) -> str:
    """Read a committed Git snapshot without waiting for workspace writers."""
    repo = get_repo(workspace)
    if not repo:
        raise FileNotFoundError(f"Git repository not found: {workspace}")
    try:
        content = repo.git.show(f"{ref}:{filepath}")
    except GitCommandError as exc:
        raise FileNotFoundError(f"File not found in {ref}: {filepath}") from exc
    if len(content) > max_size * 2:
        return f"// File too large ({len(content)} chars, max {max_size * 2})"
    return content[:max_size]


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
