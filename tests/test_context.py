"""Tests for the context-building module."""

from pathlib import Path

import pytest

from agent.context import build_file_tree, read_project_files, build_system_prompt


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    """A tiny project tree for testing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello(): pass\n")
    (tmp_path / "src" / "utils.py").write_text("def add(a, b): return a + b\n")
    (tmp_path / "README.md").write_text("# Sample\n")
    # These should be ignored
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00\x01")
    (tmp_path / ".env").write_text("SECRET=abc\n")
    return tmp_path


def test_build_file_tree_includes_source(sample_project):
    tree = build_file_tree(sample_project)
    assert "main.py" in tree
    assert "utils.py" in tree
    assert "README.md" in tree


def test_build_file_tree_excludes_pycache(sample_project):
    tree = build_file_tree(sample_project)
    assert "__pycache__" not in tree


def test_read_project_files_returns_content(sample_project):
    content = read_project_files(sample_project)
    assert "def hello()" in content
    assert "def add(" in content


def test_read_project_files_skips_dotenv(sample_project):
    content = read_project_files(sample_project)
    assert "SECRET=abc" not in content


def test_read_project_files_respects_max_chars(sample_project):
    content = read_project_files(sample_project, max_chars=50)
    assert len(content) <= 200  # some header overhead allowed


def test_build_system_prompt_structure(sample_project):
    prompt = build_system_prompt(sample_project)
    assert "## Project Structure" in prompt
    assert "## File Contents" in prompt
    assert "main.py" in prompt
