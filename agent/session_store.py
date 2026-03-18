"""
Session history store.

Persists every coding-agent chat session to local JSON files and builds a
lightweight vector index (Ollama embeddings) so sessions can be searched
semantically.

Storage layout
--------------
~/.coding-agent/
  sessions/
    2025-03-18_143022_abc12345.json   ← one file per session
  session_index.json                  ← embedding index (id + summary + vector)

Usage
-----
    store = SessionStore()
    session_id = store.save_session(messages, directory="/my/project", engine=engine)
    sessions   = store.list_sessions(n=10)
    results    = store.search_sessions("fixed authentication bug")
    full       = store.get_session("abc12345")
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Storage paths ──────────────────────────────────────────────────────────────
_BASE_DIR    = Path.home() / ".coding-agent"
SESSIONS_DIR = _BASE_DIR / "sessions"
INDEX_FILE   = _BASE_DIR / "session_index.json"

# Default embed model — nomic-embed-text is lightweight & accurate.
# Falls back to DEFAULT_MODEL if not installed.
DEFAULT_EMBED_MODEL = "nomic-embed-text"


# ── Math helpers ───────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    ma   = math.sqrt(sum(x * x for x in a))
    mb   = math.sqrt(sum(x * x for x in b))
    return dot / (ma * mb) if ma and mb else 0.0


def _keyword_score(query: str, text: str) -> float:
    words = query.lower().split()
    tl    = text.lower()
    return sum(1 for w in words if w in tl) / max(len(words), 1)


# ── SessionStore ───────────────────────────────────────────────────────────────

class SessionStore:
    """
    Thread-safe (single-process) session history with Ollama vector search.
    """

    def __init__(self, embed_model: str = DEFAULT_EMBED_MODEL) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model
        self._index: list[dict[str, Any]] = self._load_index()

    # ── Index persistence ──────────────────────────────────────────────────────

    def _load_index(self) -> list[dict[str, Any]]:
        if INDEX_FILE.exists():
            try:
                return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return []
        return []

    def _save_index(self) -> None:
        INDEX_FILE.write_text(
            json.dumps(self._index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Ollama embeddings ──────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float] | None:
        """Generate an embedding via Ollama. Returns None on failure."""
        import importlib
        try:
            import ollama
        except ImportError:
            return None
        try:
            resp = ollama.embeddings(model=self.embed_model, prompt=text)
            return resp.get("embedding") or resp.embedding  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            # Try the default model as fallback
            try:
                from .config import DEFAULT_MODEL
                resp = ollama.embeddings(model=DEFAULT_MODEL, prompt=text)
                return resp.get("embedding") or resp.embedding  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                return None

    # ── Public API ─────────────────────────────────────────────────────────────

    def save_session(
        self,
        messages: list[dict[str, str]],
        directory: str,
        engine: Any = None,
    ) -> str:
        """
        Persist a chat session to disk and add it to the index.

        Parameters
        ----------
        messages:  List of {"role": "user"|"assistant", "content": "..."} dicts.
        directory: Project root directory used during the session.
        engine:    CodingEngine instance used to auto-generate a summary.

        Returns
        -------
        session_id  8-char hex string
        """
        if not messages:
            return ""

        session_id = uuid.uuid4().hex[:8]
        now        = datetime.now()

        # ── Auto-summarise via LLM ─────────────────────────────────────────────
        summary = ""
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        if engine and user_msgs:
            try:
                summary = engine.complete(
                    "Summarise this coding session in ONE sentence (≤120 chars). "
                    "Focus on what was built or fixed:\n\n"
                    + "\n".join(f"- {t[:200]}" for t in user_msgs[:5]),
                    temperature=0.1,
                ).strip()[:200]
            except Exception:  # noqa: BLE001
                pass
        if not summary:
            summary = (user_msgs[0][:120] if user_msgs else "Coding session")

        # ── Write session file ─────────────────────────────────────────────────
        session: dict[str, Any] = {
            "id":            session_id,
            "started_at":    now.isoformat(),
            "directory":     directory,
            "message_count": len(messages),
            "summary":       summary,
            "messages":      messages,
        }
        fname = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{session_id}.json"
        (SESSIONS_DIR / fname).write_text(
            json.dumps(session, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # ── Build index entry with embedding ──────────────────────────────────
        embedding = self._embed(summary)
        entry: dict[str, Any] = {
            "id":            session_id,
            "filename":      fname,
            "started_at":    now.isoformat(),
            "directory":     directory,
            "message_count": len(messages),
            "summary":       summary,
        }
        if embedding:
            entry["embedding"] = embedding

        self._index.append(entry)
        self._save_index()
        return session_id

    def list_sessions(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the *n* most recent sessions (no messages, no embeddings)."""
        entries = sorted(self._index, key=lambda x: x.get("started_at", ""), reverse=True)
        return [_strip_embedding(e) for e in entries[:n]]

    def search_sessions(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """
        Semantic search over session summaries.

        If Ollama embeddings are available uses cosine similarity; otherwise
        falls back to keyword scoring.
        """
        if not self._index:
            return []

        query_emb = self._embed(query)

        if query_emb:
            # Semantic search — only entries that have embeddings
            scored = [
                (_cosine(query_emb, e["embedding"]), e)
                for e in self._index
                if "embedding" in e
            ]
            # Mix in keyword score for entries without embeddings
            scored += [
                (_keyword_score(query, e.get("summary", "")), e)
                for e in self._index
                if "embedding" not in e
            ]
        else:
            # Keyword fallback
            scored = [
                (_keyword_score(query, e.get("summary", "")), e)
                for e in self._index
            ]

        scored.sort(key=lambda x: x[0], reverse=True)
        return [_strip_embedding(e) for _, e in scored[:top_k]]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a full session (including messages) by its 8-char id."""
        for entry in self._index:
            if entry["id"] == session_id:
                fpath = SESSIONS_DIR / entry["filename"]
                if fpath.exists():
                    try:
                        return json.loads(fpath.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        return None
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file and remove it from the index."""
        for i, entry in enumerate(self._index):
            if entry["id"] == session_id:
                fpath = SESSIONS_DIR / entry["filename"]
                try:
                    fpath.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
                self._index.pop(i)
                self._save_index()
                return True
        return False

    def stats(self) -> dict[str, Any]:
        """Return summary stats about stored sessions."""
        return {
            "total_sessions":  len(self._index),
            "sessions_dir":    str(SESSIONS_DIR),
            "index_file":      str(INDEX_FILE),
            "embed_model":     self.embed_model,
            "indexed_with_embeddings": sum(1 for e in self._index if "embedding" in e),
        }


# ── Module-level singleton ─────────────────────────────────────────────────────

_store: SessionStore | None = None


def get_store() -> SessionStore:
    """Return the module-level SessionStore singleton."""
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_embedding(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "embedding"}
