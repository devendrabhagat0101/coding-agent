"""
coding-agent MCP server.

Exposes the coding-agent's file, git, and AI capabilities as MCP tools
so that Claude (or any MCP-compatible AI) can call them directly.

Start the server
----------------
    coding-agent mcp-serve                  # uses cwd as project root
    coding-agent mcp-serve --dir /path/to/project

Register with Claude Code (~/.claude/mcp.json)
----------------------------------------------
    {
      "mcpServers": {
        "coding-agent": {
          "command": "coding-agent",
          "args": ["mcp-serve", "--dir", "/path/to/your/project"]
        }
      }
    }

MCP primitives implemented
--------------------------
  Tools     (AI takes action):
    File : read_file, write_file, list_files, get_diff
    Git  : git_status, create_branch, commit_changes,
           push_branch, add_remote, list_remotes
    AI   : review_file, refactor_file, apply_edit   (require Ollama)

  Resources (AI browses passively — no side effects):
    project://tree              full file tree
    project://file/{path}       any file content by path
    git://status                branch + diff
    git://log                   last 20 commits
    git://branches              all local branches

  Prompts   (reusable instruction templates):
    review_file(file_path)                  numbered code review
    write_commit_message()                  conventional commit from staged diff
    explain_code(file_path)                 plain-English explanation
    fix_issue(file_path, issue_description) minimal targeted fix
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import CODER_MODEL, DEFAULT_MODEL
from .context import build_file_tree, read_project_files
from . import git_ops
from . import fixer as _fixer

mcp = FastMCP(
    "coding-agent",
    instructions=(
        "coding-agent gives you full read/write access to a local project directory "
        "plus git operations (branch, commit, push) and optional Ollama-powered "
        "code review and refactoring. "
        "All path arguments are relative to the project root unless absolute."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _root(root_arg: str) -> Path:
    """Resolve the project root: use arg if provided, else cwd."""
    return Path(root_arg).resolve() if root_arg else Path.cwd().resolve()


def _resolve(root: Path, path_arg: str) -> Path:
    p = Path(path_arg)
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **data}


def _err(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

@mcp.tool()
def read_file(path: str, root: str = "") -> dict:
    """
    Read a file and return its content.

    Args:
        path: Path to file (relative to root or absolute).
        root: Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        target = _resolve(r, path)
        if not target.exists():
            return _err(f"File not found: {target}")
        content = target.read_text(encoding="utf-8", errors="replace")
        rel = str(target.relative_to(r)) if target.is_relative_to(r) else str(target)
        return _ok({"path": rel, "content": content, "lines": content.count("\n") + 1})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def write_file(path: str, content: str, root: str = "") -> dict:
    """
    Write (overwrite) a file with the given content.

    Args:
        path:    Path to file (relative to root or absolute).
        content: Full file content to write.
        root:    Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        target = _resolve(r, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        rel = str(target.relative_to(r)) if target.is_relative_to(r) else str(target)
        return _ok({"path": rel, "bytes_written": len(content.encode())})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def list_files(root: str = "") -> dict:
    """
    Return the project file tree and a summary of all text file paths.

    Args:
        root: Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        tree = build_file_tree(r)
        return _ok({"root": str(r), "tree": tree})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def get_diff(root: str = "", staged: bool = False) -> dict:
    """
    Return the current git diff (unstaged by default).

    Args:
        root:   Project root directory (default: cwd).
        staged: If true, return staged (--cached) diff instead.
    """
    try:
        r = _root(root)
        diff = git_ops.get_diff(r, staged=staged)
        return _ok({"diff": diff or "(no changes)", "staged": staged})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Git tools
# ---------------------------------------------------------------------------

@mcp.tool()
def git_status(root: str = "") -> dict:
    """
    Return the current branch name and a status summary.

    Args:
        root: Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        repo = git_ops.get_repo(r)
        if repo is None:
            return _err(f"No git repository found at or above: {r}")
        branch  = git_ops.current_branch(r)
        summary = git_ops.status_summary(r)
        return _ok({"branch": branch, "status": summary})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def create_branch(name: str, root: str = "") -> dict:
    """
    Create and checkout a new git branch from HEAD.

    Args:
        name: Branch name to create.
        root: Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        git_ops.create_branch(r, name)
        return _ok({"branch": name, "message": f"Switched to branch '{name}'"})
    except (ValueError, Exception) as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def commit_changes(
    message: str,
    files: list[str] | None = None,
    root: str = "",
) -> dict:
    """
    Stage files (or all changes) and create a git commit.

    Args:
        message: Commit message.
        files:   List of file paths to stage (default: all changes).
        root:    Project root directory (default: cwd).
    """
    try:
        r      = _root(root)
        staged = [str(_resolve(r, f)) for f in files] if files else None
        sha    = git_ops.commit_changes(r, message, files=staged)
        return _ok({"sha": sha, "message": message})
    except (ValueError, RuntimeError, Exception) as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def push_branch(branch: str = "", remote: str = "origin", root: str = "") -> dict:
    """
    Push the current (or named) branch to a remote.

    Args:
        branch: Branch to push (default: active branch).
        remote: Remote name (default: origin).
        root:   Project root directory (default: cwd).
    """
    try:
        r   = _root(root)
        url = git_ops.push_branch(r, branch=branch or None, remote=remote)
        pushed = branch or git_ops.current_branch(r)
        return _ok({"branch": pushed, "remote": remote, "url": url})
    except (ValueError, Exception) as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def add_remote(name: str, url: str, root: str = "") -> dict:
    """
    Add a new git remote.

    Args:
        name: Remote name (e.g. 'origin').
        url:  Remote URL (e.g. 'https://github.com/user/repo.git').
        root: Project root directory (default: cwd).
    """
    try:
        r = _root(root)
        git_ops.add_remote(r, name, url)
        return _ok({"name": name, "url": url})
    except (ValueError, Exception) as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def list_remotes(root: str = "") -> dict:
    """
    List all configured git remotes.

    Args:
        root: Project root directory (default: cwd).
    """
    try:
        r       = _root(root)
        remotes = git_ops.list_remotes(r)
        return _ok({"remotes": [{"name": n, "url": u} for n, u in remotes]})
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


# ---------------------------------------------------------------------------
# AI tools  (require Ollama — graceful error if unavailable)
# ---------------------------------------------------------------------------

def _get_engine(model: str):
    """Return a CodingEngine or raise a descriptive error."""
    from .engine import CodingEngine, OllamaUnavailableError
    engine = CodingEngine(model=model)
    available = engine.list_local_models()
    if not available:
        raise RuntimeError(
            "Ollama is not running. Start it with: ollama serve"
        )
    if model not in available:
        raise RuntimeError(
            f"Model '{model}' not found locally. "
            f"Available: {', '.join(available)}. "
            f"Pull with: ollama pull {model}"
        )
    return engine


@mcp.tool()
def review_file(path: str, model: str = CODER_MODEL, root: str = "") -> dict:
    """
    AI-powered code review — returns a numbered list of bugs and improvements.

    Uses the local Ollama model (requires ollama serve).

    Args:
        path:  File to review (relative to root or absolute).
        model: Ollama model to use (default: qwen2.5-coder:7b).
        root:  Project root directory (default: cwd).
    """
    try:
        r       = _root(root)
        target  = _resolve(r, path)
        if not target.exists():
            return _err(f"File not found: {target}")

        source  = target.read_text(encoding="utf-8", errors="replace")
        lang    = target.suffix.lstrip(".") or "text"
        rel     = str(target.relative_to(r)) if target.is_relative_to(r) else str(target)
        engine  = _get_engine(model)

        system = (
            "You are a senior software engineer doing a code review. "
            "Be precise and actionable. Focus on real bugs and meaningful improvements."
        )
        prompt = (
            f"Review `{rel}` for bugs, security issues, and improvements.\n\n"
            "Format as a numbered list. For each item:\n"
            "  - **Issue**: what is wrong\n"
            "  - **Location**: function name or line reference\n"
            "  - **Fix**: exact change needed\n\n"
            "End with a one-line overall quality verdict.\n\n"
            f"```{lang}\n{source}\n```"
        )
        review = engine.complete(prompt, system=system, temperature=0.2)
        return _ok({"path": rel, "review": review, "model": model})

    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def refactor_file(
    path: str,
    instruction: str = "",
    model: str = CODER_MODEL,
    root: str = "",
) -> dict:
    """
    AI-powered file refactor — returns the improved file content.

    The caller should use write_file + commit_changes to persist the result.

    Args:
        path:        File to refactor (relative to root or absolute).
        instruction: Refactor goal (default: readability + best practices).
        model:       Ollama model to use (default: qwen2.5-coder:7b).
        root:        Project root directory (default: cwd).
    """
    try:
        r       = _root(root)
        target  = _resolve(r, path)
        if not target.exists():
            return _err(f"File not found: {target}")

        source  = target.read_text(encoding="utf-8", errors="replace")
        lang    = target.suffix.lstrip(".") or "text"
        rel     = str(target.relative_to(r)) if target.is_relative_to(r) else str(target)
        goal    = instruction or "Improve readability, add type hints and docstrings, follow best practices."
        engine  = _get_engine(model)

        system = (
            "You are an expert software engineer specialising in code refactoring. "
            "Return ONLY the refactored code inside a single fenced code block. "
            "Do not add explanations outside the block."
        )
        prompt = (
            f"Refactor `{rel}` ({lang}).\n\n"
            f"**Goal:** {goal}\n\n"
            f"```{lang}\n{source}\n```"
        )
        reply  = engine.complete(prompt, system=system, temperature=0.1)

        import re
        blocks = re.findall(r"```(?:\w*)\n(.*?)```", reply, re.DOTALL)
        refactored = (blocks[0].rstrip() + "\n") if blocks else reply.strip() + "\n"

        diff = _fixer.unified_diff(source, refactored, target.name)
        return _ok({
            "path": rel,
            "refactored_content": refactored,
            "diff": diff or "(no changes)",
            "model": model,
        })

    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


@mcp.tool()
def apply_edit(path: str, instruction: str, model: str = CODER_MODEL, root: str = "") -> dict:
    """
    Apply a targeted code change to a file using AI.

    The caller should use write_file + commit_changes to persist the result.

    Args:
        path:        File to edit (relative to root or absolute).
        instruction: Description of the change (e.g. 'add null check in process()').
        model:       Ollama model to use (default: qwen2.5-coder:7b).
        root:        Project root directory (default: cwd).
    """
    try:
        r      = _root(root)
        target = _resolve(r, path)
        if not target.exists():
            return _err(f"File not found: {target}")

        source  = target.read_text(encoding="utf-8", errors="replace")
        rel     = str(target.relative_to(r)) if target.is_relative_to(r) else str(target)
        engine  = _get_engine(model)

        fixed  = _fixer.apply_fix_with_engine(engine, target, instruction, instruction)
        diff   = _fixer.unified_diff(source, fixed, target.name)

        return _ok({
            "path": rel,
            "updated_content": fixed,
            "diff": diff or "(no changes)",
            "model": model,
        })

    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Document writer tool  (v2.0.2)
# ---------------------------------------------------------------------------

@mcp.tool()
def write_document(
    instruction: str,
    output_path: str,
    model: str = CODER_MODEL,
    root: str = "",
) -> dict:
    """
    Generate and write a rich document from a natural language instruction.

    Supports: .docx (Word), .pptx (PowerPoint), .xlsx (Excel),
              .pdf, .md (Markdown), .txt, .csv

    Args:
        instruction:  What to write, e.g. "Project summary with architecture section".
        output_path:  Destination file path. Extension determines the format.
        model:        Ollama model to use (default: qwen2.5-coder:7b).
        root:         Project root for context (default: cwd).
    """
    try:
        from .file_writer import write_document as _write_doc, SUPPORTED_FORMATS
        r   = _root(root)
        out = _resolve(r, output_path)

        fmt = out.suffix.lower()
        if fmt not in SUPPORTED_FORMATS:
            return _err(
                f"Unsupported format: {fmt}. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        engine = _get_engine(model)

        # Load project context
        from .context import read_project_files
        context = read_project_files(r)

        result = _write_doc(
            instruction=instruction,
            output=out,
            engine=engine,
            context=context,
        )

        rel = str(result.relative_to(r)) if result.is_relative_to(r) else str(result)
        return _ok({
            "path":   rel,
            "format": fmt,
            "bytes":  result.stat().st_size,
            "model":  model,
        })

    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Resources  (read-only browsable data — no side effects)
# ---------------------------------------------------------------------------

@mcp.resource("project://tree")
def resource_project_tree() -> str:
    """
    Browse the full project file tree.

    Use this to understand the project structure before deciding which files
    to read or edit. Returns an ASCII directory tree.
    """
    return build_file_tree(Path.cwd().resolve())


@mcp.resource("project://file/{path}")
def resource_read_file(path: str) -> str:
    """
    Read the content of any project file by path.

    URI format:  project://file/agents/payment_agent.py
                 project://file/frontend/lib/screens/chat_screen.dart

    Returns the raw file content as text. Binary files return an error message.
    """
    try:
        target = (Path.cwd() / path).resolve()
        if not target.exists():
            return f"ERROR: file not found — {path}"
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


@mcp.resource("git://status")
def resource_git_status() -> str:
    """
    Current git branch and working-tree status (modified / staged / untracked files).
    Use this before committing or branching to understand the current state.
    """
    try:
        r = Path.cwd().resolve()
        branch  = git_ops.current_branch(r)
        summary = git_ops.status_summary(r)
        diff    = git_ops.get_diff(r, staged=False)
        staged  = git_ops.get_diff(r, staged=True)
        return (
            f"Branch: {branch}\n"
            f"Status: {summary}\n\n"
            f"--- Unstaged changes ---\n{diff or '(none)'}\n\n"
            f"--- Staged changes ---\n{staged or '(none)'}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


@mcp.resource("git://log")
def resource_git_log() -> str:
    """
    Recent git commit history (last 20 commits).
    Use this to understand what has changed recently before making new commits.
    """
    try:
        repo = git_ops.require_repo(Path.cwd().resolve())
        commits = list(repo.iter_commits(max_count=20))
        lines = [
            f"{c.hexsha[:7]}  {c.authored_datetime.strftime('%Y-%m-%d')}  {c.summary}"
            for c in commits
        ]
        return "\n".join(lines) if lines else "(no commits)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


@mcp.resource("git://branches")
def resource_git_branches() -> str:
    """
    All local git branches and which one is currently checked out.
    """
    try:
        r      = Path.cwd().resolve()
        active = git_ops.current_branch(r)
        all_br = git_ops.list_branches(r)
        return "\n".join(
            f"{'* ' if b == active else '  '}{b}" for b in all_br
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Prompts  (reusable instruction templates the AI fills in)
# ---------------------------------------------------------------------------

@mcp.prompt()
def prompt_review_file(file_path: str) -> str:
    """
    Load the code-review prompt template for a specific file.

    The AI reads the file content and returns a numbered list of
    bugs, security issues, and improvements with suggested fixes.
    """
    try:
        content = (Path.cwd() / file_path).read_text(encoding="utf-8", errors="replace")
        lang    = Path(file_path).suffix.lstrip(".") or "text"
    except Exception:  # noqa: BLE001
        content = f"(could not read {file_path})"
        lang    = "text"

    return (
        f"Review `{file_path}` for bugs, security issues, and improvements.\n\n"
        "Format as a numbered list. For each item:\n"
        "  - **Issue**: what is wrong\n"
        "  - **Location**: function name or line reference\n"
        "  - **Fix**: exact change needed\n\n"
        "End with a one-line overall quality verdict.\n\n"
        f"```{lang}\n{content}\n```"
    )


@mcp.prompt()
def prompt_write_commit_message() -> str:
    """
    Generate a conventional commit message for all staged changes.

    Reads the staged diff and produces a short imperative commit message
    following the Conventional Commits spec (feat/fix/chore/refactor/docs).
    """
    try:
        diff = git_ops.get_diff(Path.cwd().resolve(), staged=True)
    except Exception:  # noqa: BLE001
        diff = "(could not read staged diff)"

    return (
        "Write a git commit message for the following staged changes.\n\n"
        "Rules:\n"
        "  - First line: type(scope): short description  (≤72 chars, imperative mood)\n"
        "  - Types: feat | fix | chore | refactor | docs | test | style\n"
        "  - Second paragraph (optional): explain WHY, not what\n"
        "  - No bullet points in the subject line\n\n"
        f"Staged diff:\n```diff\n{diff or '(nothing staged)'}\n```\n\n"
        "Output ONLY the commit message — no explanation."
    )


@mcp.prompt()
def prompt_explain_code(file_path: str) -> str:
    """
    Explain what a file does in plain English.

    Useful for onboarding, documentation, or understanding unfamiliar code.
    """
    try:
        content = (Path.cwd() / file_path).read_text(encoding="utf-8", errors="replace")
        lang    = Path(file_path).suffix.lstrip(".") or "text"
    except Exception:  # noqa: BLE001
        content = f"(could not read {file_path})"
        lang    = "text"

    return (
        f"Explain `{file_path}` in plain English.\n\n"
        "Cover:\n"
        "  1. What this file does (one paragraph)\n"
        "  2. Key functions/classes and their purpose\n"
        "  3. How it connects to the rest of the project\n"
        "  4. Any gotchas or non-obvious behaviour\n\n"
        f"```{lang}\n{content}\n```"
    )


@mcp.prompt()
def prompt_fix_issue(file_path: str, issue_description: str) -> str:
    """
    Apply a targeted fix to a specific issue in a file.

    Reads the file, describes the issue, and asks for the minimal change needed.
    """
    try:
        content = (Path.cwd() / file_path).read_text(encoding="utf-8", errors="replace")
        lang    = Path(file_path).suffix.lstrip(".") or "text"
    except Exception:  # noqa: BLE001
        content = f"(could not read {file_path})"
        lang    = "text"

    return (
        f"Fix the following issue in `{file_path}`.\n\n"
        f"**Issue:** {issue_description}\n\n"
        "Rules:\n"
        "  - Make the minimal change needed — do not refactor unrelated code\n"
        "  - Return the COMPLETE updated file in a single fenced code block\n"
        "  - No explanation outside the code block\n\n"
        f"Current file:\n```{lang}\n{content}\n```"
    )


# ---------------------------------------------------------------------------
# Entry point (called by the CLI subcommand)
# ---------------------------------------------------------------------------

def serve(project_root: str | None = None) -> None:
    """Start the MCP server. Called by `coding-agent mcp-serve`."""
    if project_root:
        os.chdir(project_root)
    mcp.run()
