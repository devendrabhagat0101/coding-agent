"""Tests for the Ollama engine wrapper (mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from agent.engine import CodingEngine, OllamaUnavailableError


@pytest.fixture()
def engine():
    return CodingEngine(model="llama3.1")


def _make_chunk(token: str) -> dict:
    return {"message": {"content": token}}


def test_add_system_inserts_at_front(engine):
    engine.add_system("be helpful")
    assert engine._history[0] == {"role": "system", "content": "be helpful"}


def test_add_system_replaces_existing(engine):
    engine.add_system("first")
    engine.add_system("second")
    system_msgs = [m for m in engine._history if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "second"


def test_stream_chat_yields_tokens(engine):
    chunks = [_make_chunk("Hello"), _make_chunk(" world")]

    with patch("ollama.chat", return_value=iter(chunks)):
        tokens = list(engine.stream_chat("hi"))

    assert tokens == ["Hello", " world"]


def test_stream_chat_appends_history(engine):
    chunks = [_make_chunk("Sure!")]

    with patch("ollama.chat", return_value=iter(chunks)):
        list(engine.stream_chat("Can you help?"))

    roles = [m["role"] for m in engine._history]
    assert roles == ["user", "assistant"]
    assert engine._history[-1]["content"] == "Sure!"


def test_stream_chat_raises_on_ollama_error(engine):
    with patch("ollama.chat", side_effect=ConnectionRefusedError("refused")):
        with pytest.raises(OllamaUnavailableError):
            list(engine.stream_chat("hello"))


def test_clear_history(engine):
    engine._history.append({"role": "user", "content": "test"})
    engine.clear_history()
    assert engine._history == []


def test_complete_returns_string(engine):
    mock_response = {"message": {"content": "refactor: improve readability"}}

    with patch("ollama.chat", return_value=mock_response):
        result = engine.complete("write a commit message")

    assert result == "refactor: improve readability"


def test_list_local_models_returns_names(engine):
    with patch("ollama.list", return_value={"models": [{"name": "llama3.1"}, {"name": "qwen2.5-coder:7b"}]}):
        models = engine.list_local_models()

    assert "llama3.1" in models
    assert "qwen2.5-coder:7b" in models


def test_list_local_models_empty_on_error(engine):
    with patch("ollama.list", side_effect=Exception("no server")):
        models = engine.list_local_models()

    assert models == []
