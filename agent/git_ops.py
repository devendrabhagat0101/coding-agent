"""
Git operations via GitPython.

Exposes simple functions so the CLI layer never imports git directly.
"""

from __future__ import annotations

from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo


# ---------------------------------------------------------------------------
# Repo discovery
# ---------------------------------------------------------------------------

def get_repo(path: Path) -> Repo | None:
    """Return the Repo for *path* (or any parent), or None if not in a repo."""
    try:
        return Repo(path, search_parent_directories=True)
    except InvalidGitRepositoryError:
        return None


def require_repo(path: Path) -> Repo:
    repo = get_repo(path)
    if repo is None:
        raise ValueError(f"No git repository found at or above: {path}")
    return repo


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_repo(
    path: Path,
    *,
    initial_branch: str = "main",
    gitignore_extras: list[str] | None = None,
) -> Repo:
    """
    Create a new git repo at *path*.

    Also writes a sensible .gitignore and makes an initial empty commit
    so the repo is in a clean, usable state right away.
    """
    path.mkdir(parents=True, exist_ok=True)

    repo = Repo.init(path, initial_branch=initial_branch)

    # .gitignore
    default_ignores = [
        "__pycache__/",
        "*.py[cod]",
        ".venv/",
        "venv/",
        "env/",
        ".env",
        "*.egg-info/",
        "dist/",
        "build/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".ruff_cache/",
        "node_modules/",
        ".DS_Store",
    ]
    if gitignore_extras:
        default_ignores.extend(gitignore_extras)

    gitignore = path / ".gitignore"
    gitignore.write_text("\n".join(default_ignores) + "\n")

    repo.index.add([".gitignore"])
    repo.index.commit("chore: initial commit")

    return repo


# ---------------------------------------------------------------------------
# Branch management
# ---------------------------------------------------------------------------

def create_branch(repo_path: Path, branch_name: str, *, checkout: bool = True) -> str:
    """
    Create *branch_name* from HEAD and optionally check it out.

    Returns the full branch name (unchanged — useful for confirmation).
    """
    repo = require_repo(repo_path)

    if branch_name in [b.name for b in repo.branches]:  # type: ignore[attr-defined]
        raise ValueError(f"Branch '{branch_name}' already exists.")

    new_branch = repo.create_head(branch_name)
    if checkout:
        new_branch.checkout()

    return branch_name


def current_branch(repo_path: Path) -> str:
    repo = require_repo(repo_path)
    return repo.active_branch.name


def list_branches(repo_path: Path) -> list[str]:
    repo = require_repo(repo_path)
    return [b.name for b in repo.branches]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Staging & committing
# ---------------------------------------------------------------------------

def commit_changes(
    repo_path: Path,
    message: str,
    files: list[str] | None = None,
) -> str:
    """
    Stage *files* (or all tracked/untracked changes if None) and commit.

    Returns the short SHA of the new commit.
    """
    repo = require_repo(repo_path)

    if files:
        repo.index.add(files)
    else:
        # Stage everything: modified, new, deleted
        repo.git.add(A=True)

    if not repo.index.diff("HEAD") and not repo.untracked_files:
        raise ValueError("Nothing to commit — working tree is clean.")

    try:
        commit = repo.index.commit(message)
    except GitCommandError as exc:
        raise RuntimeError(f"Git commit failed: {exc}") from exc

    return repo.git.rev_parse("--short", commit.hexsha)


# ---------------------------------------------------------------------------
# Remote management & push
# ---------------------------------------------------------------------------

def list_remotes(repo_path: Path) -> list[tuple[str, str]]:
    """Return [(name, url), ...] for all configured remotes."""
    repo = require_repo(repo_path)
    return [(r.name, r.url) for r in repo.remotes]


def add_remote(repo_path: Path, name: str, url: str) -> None:
    """Add a new remote named *name* pointing at *url*."""
    repo = require_repo(repo_path)
    existing = [r.name for r in repo.remotes]
    if name in existing:
        raise ValueError(f"Remote '{name}' already exists.")
    repo.create_remote(name, url)


def push_branch(
    repo_path: Path,
    branch: str | None = None,
    remote: str = "origin",
) -> str:
    """
    Push *branch* (defaults to active branch) to *remote*.

    Sets upstream on first push so subsequent pushes need no args.
    Returns the remote URL for confirmation display.
    """
    repo = require_repo(repo_path)
    if not repo.remotes:
        raise ValueError(
            "No remotes configured. "
            "Add one first: /remote add origin https://github.com/user/repo.git"
        )
    try:
        remote_obj = repo.remote(remote)
    except ValueError:
        raise ValueError(
            f"Remote '{remote}' not found. "
            f"Available: {', '.join(r.name for r in repo.remotes)}"
        ) from None

    branch_name = branch or repo.active_branch.name
    repo.git.push("--set-upstream", remote, branch_name)
    return remote_obj.url


# ---------------------------------------------------------------------------

def get_diff(repo_path: Path, staged: bool = False) -> str:
    """Return the current diff as a string (unstaged by default)."""
    repo = require_repo(repo_path)
    if staged:
        return repo.git.diff("--cached")
    return repo.git.diff()


def status_summary(repo_path: Path) -> str:
    """One-liner status string, e.g. '2 modified, 1 untracked'."""
    repo = require_repo(repo_path)
    parts: list[str] = []
    diff = repo.index.diff(None)
    if diff:
        parts.append(f"{len(diff)} modified")
    if repo.untracked_files:
        parts.append(f"{len(repo.untracked_files)} untracked")
    staged = repo.index.diff("HEAD")
    if staged:
        parts.append(f"{len(staged)} staged")
    return ", ".join(parts) if parts else "clean"
