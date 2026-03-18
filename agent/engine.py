"""
Thin wrapper around the `ollama` Python library.

Handles:
  - Streaming chat with configurable model
  - One-shot completion (non-streaming)
  - Graceful error surfacing when Ollama is not running
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import ollama

from .config import DEFAULT_MODEL


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama daemon cannot be reached."""


class CodingEngine:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        # message history for multi-turn chat (role + content dicts)
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_model(self, model: str) -> None:
        self.model = model

    def clear_history(self) -> None:
        self._history.clear()

    def add_system(self, content: str) -> None:
        """Prepend (or replace) the system message in history."""
        if self._history and self._history[0]["role"] == "system":
            self._history[0]["content"] = content
        else:
            self._history.insert(0, {"role": "system", "content": content})

    def stream_chat(
        self,
        user_message: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> Generator[str, None, None]:
        """
        Send *user_message* and yield response tokens one-by-one.

        If *system* is provided it sets/replaces the system message for
        this call.  The full conversation is kept in ``self._history`` so
        subsequent calls maintain context.
        """
        if system is not None:
            self.add_system(system)

        self._history.append({"role": "user", "content": user_message})

        try:
            stream = ollama.chat(
                model=self.model,
                messages=self._history,
                stream=True,
                options={"temperature": temperature},
            )
        except Exception as exc:  # noqa: BLE001
            raise OllamaUnavailableError(
                f"Could not reach Ollama ({exc}). "
                "Is `ollama serve` running?"
            ) from exc

        full_response: list[str] = []
        for chunk in stream:
            token: str = chunk["message"]["content"]
            full_response.append(token)
            yield token

        # Persist assistant turn for next round
        self._history.append(
            {"role": "assistant", "content": "".join(full_response)}
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.1,
    ) -> str:
        """
        Non-streaming one-shot completion.  Useful for structured outputs
        (e.g. generating a commit message or branch name).
        """
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                stream=False,
                options={"temperature": temperature},
            )
        except Exception as exc:  # noqa: BLE001
            raise OllamaUnavailableError(
                f"Could not reach Ollama ({exc}). "
                "Is `ollama serve` running?"
            ) from exc

        return response["message"]["content"]

    def list_local_models(self) -> list[str]:
        """Return the names of all models pulled locally."""
        try:
            result = ollama.list()
            models = result.get("models", []) if isinstance(result, dict) else list(result.models)
            names = []
            for m in models:
                # newer ollama library uses "model" key; older used "name"
                if isinstance(m, dict):
                    names.append(m.get("model") or m.get("name") or "")
                else:
                    names.append(getattr(m, "model", None) or getattr(m, "name", "") or "")
            return [n for n in names if n]
        except Exception:  # noqa: BLE001
            return []
