"""Tests for git_ops helpers."""

from pathlib import Path

import pytest

from agent import git_ops


@pytest.fixture()
def fresh_repo(tmp_path: Path):
    return git_ops.init_repo(tmp_path / "myrepo")


def test_init_creates_directory(tmp_path):
    repo = git_ops.init_repo(tmp_path / "proj")
    assert (tmp_path / "proj").is_dir()


def test_init_creates_gitignore(tmp_path):
    git_ops.init_repo(tmp_path / "proj")
    assert (tmp_path / "proj" / ".gitignore").exists()


def test_init_makes_initial_commit(fresh_repo):
    commits = list(fresh_repo.iter_commits())
    assert len(commits) == 1
    assert "initial commit" in commits[0].message


def test_create_branch(fresh_repo):
    branch = git_ops.create_branch(fresh_repo.working_dir, "feature/test")
    assert branch == "feature/test"
    assert git_ops.current_branch(fresh_repo.working_dir) == "feature/test"


def test_create_duplicate_branch_raises(fresh_repo):
    git_ops.create_branch(fresh_repo.working_dir, "dupe")
    with pytest.raises(ValueError, match="already exists"):
        git_ops.create_branch(fresh_repo.working_dir, "dupe")


def test_commit_changes(fresh_repo):
    new_file = Path(fresh_repo.working_dir) / "hello.py"
    new_file.write_text("print('hi')\n")
    sha = git_ops.commit_changes(fresh_repo.working_dir, "feat: add hello")
    assert len(sha) > 0


def test_commit_nothing_raises(fresh_repo):
    with pytest.raises(ValueError, match="Nothing to commit"):
        git_ops.commit_changes(fresh_repo.working_dir, "empty")


def test_get_repo_returns_none_outside_repo(tmp_path):
    assert git_ops.get_repo(tmp_path) is None


def test_status_summary_clean(fresh_repo):
    assert git_ops.status_summary(fresh_repo.working_dir) == "clean"
