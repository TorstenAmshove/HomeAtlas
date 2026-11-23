"""#120: one chat round ends at a hard deadline with a clean, replayable transcript."""
import asyncio

import pytest

from app import db, llm_providers, tools


class _Result:
    def __init__(self, text="ok", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.provider_raw = None
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.model = "m"


def _turn(chat_id, text="hallo"):
    return asyncio.run(tools._run_chat_turn(chat_id, text, {"llmProvider": "claude"}))


def test_hanging_llm_call_ends_round(temp_db, monkeypatch):
    monkeypatch.setattr(tools, "_TURN_DEADLINE_S", 0.05)

    async def hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(llm_providers, "chat", hang)
    chat = db.create_chat("t")
    out = _turn(chat["id"])
    assert out["model"] == ""
    assert "zu lange gedauert" in out["message"]["content"]
    assert out["message"]["durationMs"] is not None


def test_hanging_tool_fills_unanswered_calls_and_next_round_works(temp_db, monkeypatch):
    monkeypatch.setattr(tools, "_TURN_DEADLINE_S", 0.05)
    calls = [{"id": "c1", "name": "ping", "arguments": {}}, {"id": "c2", "name": "ping", "arguments": {}}]

    async def fake_chat(*a, **k):
        return _Result("", calls)

    async def hang(name, args):
        await asyncio.sleep(30)

    monkeypatch.setattr(llm_providers, "chat", fake_chat)
    monkeypatch.setattr(tools, "dispatch", hang)
    chat = db.create_chat("t")
    _turn(chat["id"])
    history = tools.history_for_llm(chat["id"])
    tool_msgs = [m for m in history if m["role"] == "tool"]
    assert [(m["tool_call_id"], m["name"]) for m in tool_msgs] == [("c1", "ping"), ("c2", "ping")]
    assert all("Zeitgrenze" in m["content"] for m in tool_msgs)

    async def ok(*a, **k):
        return _Result("fertig")

    monkeypatch.setattr(tools, "_TURN_DEADLINE_S", 5)
    monkeypatch.setattr(llm_providers, "chat", ok)
    assert _turn(chat["id"], "nochmal")["message"]["content"] == "fertig"


def test_provider_error_unchanged(temp_db, monkeypatch):
    async def boom(*a, **k):
        raise llm_providers.ProviderError("kaputt")

    monkeypatch.setattr(llm_providers, "chat", boom)
    chat = db.create_chat("t")
    with pytest.raises(llm_providers.ProviderError):
        _turn(chat["id"])
