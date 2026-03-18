"""
Apply AI-suggested fixes fetched from the chatbot's pending-fix queue.

Workflow
--------
1. Poll  GET  <ai_service>/api/chat/pending-fixes?status=PENDING
2. For each fix: show analysis, ask user to confirm + supply target file
3. Use CodingEngine to apply the suggested change to the file
4. Write the result, optionally commit
5. Mark fix as APPLIED via POST <ai_service>/api/chat/pending-fixes/{id}/resolve
"""

from __future__ import annotations

import difflib
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AI_SERVICE_DEFAULT = "http://localhost:8082"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 10) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url: str, payload: dict, timeout: int = 15) -> Any:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_pending_fixes(base_url: str = AI_SERVICE_DEFAULT) -> list[dict]:
    """Return all PENDING fix requests from the AI service."""
    try:
        data = _get(f"{base_url}/api/chat/pending-fixes?status=PENDING")
        return data.get("fixes", [])
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Cannot reach AI service at {base_url}. "
            "Is `python3.11 -m uvicorn main:app --port 8082` running?"
        ) from exc


def mark_resolved(fix_id: str, action: str = "APPLIED",
                  base_url: str = AI_SERVICE_DEFAULT) -> None:
    """Tell the AI service a fix was applied or dismissed."""
    try:
        _post(
            f"{base_url}/api/chat/pending-fixes/{fix_id}/resolve",
            {"action": action, "resolved_at": datetime.now(timezone.utc).isoformat()},
        )
    except Exception:  # noqa: BLE001
        pass  # non-critical — the fix was already applied locally


def unified_diff(original: str, modified: str, filename: str) -> str:
    """Return a unified diff string between *original* and *modified*."""
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    ))


def apply_fix_with_engine(
    engine,            # CodingEngine instance
    file_path: Path,
    suggested_fix: str,
    issue_description: str,
) -> str:
    """
    Ask the LLM engine to apply *suggested_fix* to *file_path*.

    Returns the refactored file content as a string.
    """
    original = file_path.read_text(encoding="utf-8", errors="replace")
    lang     = file_path.suffix.lstrip(".") or "text"

    system = (
        "You are an expert software engineer applying a targeted bug fix.\n"
        "Return ONLY the complete fixed file inside a single fenced code block.\n"
        "Do not add explanations outside the block."
    )
    user_msg = (
        f"Apply the following fix to `{file_path.name}`.\n\n"
        f"**Issue:** {issue_description}\n\n"
        f"**Suggested fix:** {suggested_fix}\n\n"
        f"**Current file content:**\n```{lang}\n{original}\n```\n\n"
        "Return the complete fixed file."
    )

    import re
    reply  = engine.complete(user_msg, system=system, temperature=0.1)
    blocks = re.findall(r"```(?:\w*)\n(.*?)```", reply, re.DOTALL)

    if not blocks:
        # Engine returned raw code without fences — use it directly
        return reply.strip() + "\n"

    return blocks[0].rstrip() + "\n"
