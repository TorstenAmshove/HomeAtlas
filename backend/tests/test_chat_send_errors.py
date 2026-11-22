"""#150: a failed chat round leaves nothing behind, messages are trimmed, renaming only on success."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, llm_providers, main

ANNA = {"id": "u-anna", "role": auth.ROLE_MEMBER, "username": "anna", "totpEnabled": 1}


class _Result:
    def __init__(self, text="ok", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.provider_raw = None
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.model = "m"


@pytest.fixture()
def client(temp_db, monkeypatch):
    main.app.dependency_overrides[main.current_user] = lambda: ANNA
    monkeypatch.setattr(llm_providers, "is_configured", lambda *a, **k: True)
    try:
        yield TestClient(main.app, raise_server_exceptions=False)
    finally:
        main.app.dependency_overrides.clear()


def _script(monkeypatch, steps):
    """Each step is a result or an exception to raise, consumed per chat() call."""
    queue = list(steps)

    async def fake(*a, **k):
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
    monkeypatch.setattr(llm_providers, "chat", fake)


def _new_chat(client):
    return client.post("/api/chats").json()["chat"]["id"]


def _send(client, chat_id, text):
    return client.post(f"/api/chats/{chat_id}/messages", json={"message": text})


def _contents(chat_id):
    return [(m["role"], m["content"]) for m in db.list_chat_messages(chat_id)]


@pytest.mark.parametrize("text", ["", "   ", "\n\t", " "])
def test_blank_message_is_422(client, text):
    chat_id = _new_chat(client)
    assert _send(client, chat_id, text).status_code == 422
    assert db.list_chat_messages(chat_id) == []


def test_message_is_stored_trimmed(client, monkeypatch):
    _script(monkeypatch, [_Result()])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "  hallo \n").status_code == 200
    assert _contents(chat_id)[0] == ("user", "hallo")


def test_provider_error_removes_user_message(client, monkeypatch):
    _script(monkeypatch, [llm_providers.ProviderError("kaputt")])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "hi").status_code == 502
    assert db.list_chat_messages(chat_id) == []


def test_provider_error_after_tool_call_removes_whole_turn(client, monkeypatch):
    call = {"id": "c1", "name": "does_not_exist", "arguments": {}}
    _script(monkeypatch, [_Result(tool_calls=[call]), llm_providers.ProviderError("kaputt")])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "hi").status_code == 502
    assert db.list_chat_messages(chat_id) == []


def test_rollback_keeps_earlier_messages(client, monkeypatch):
    _script(monkeypatch, [_Result("eins"), llm_providers.ProviderError("kaputt")])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "a").status_code == 200
    assert _send(client, chat_id, "b").status_code == 502
    assert _contents(chat_id) == [("user", "a"), ("assistant", "eins")]


def test_resend_after_failure_has_one_user_message(client, monkeypatch):
    _script(monkeypatch, [llm_providers.ProviderError("kaputt"), _Result()])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "hi").status_code == 502
    assert _send(client, chat_id, "hi").status_code == 200
    assert [r for r, _ in _contents(chat_id)].count("user") == 1


def test_unexpected_error_also_rolls_back(client, monkeypatch):
    _script(monkeypatch, [RuntimeError("boom")])
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "hi").status_code == 500
    assert db.list_chat_messages(chat_id) == []


def test_no_key_400_keeps_chat_untouched(client, monkeypatch):
    monkeypatch.setattr(llm_providers, "is_configured", lambda *a, **k: False)
    chat_id = _new_chat(client)
    assert _send(client, chat_id, "hi").status_code == 400
    assert db.list_chat_messages(chat_id) == []
    assert db.get_chat(chat_id)["title"] == "Neue Unterhaltung"


def test_failed_first_round_keeps_chat_title(client, monkeypatch):
    _script(monkeypatch, [llm_providers.ProviderError("kaputt")])
    chat_id = _new_chat(client)
    _send(client, chat_id, "hi")
    assert db.get_chat(chat_id)["title"] == "Neue Unterhaltung"


def test_successful_first_round_renames_chat(client, monkeypatch):
    _script(monkeypatch, [_Result()])
    chat_id = _new_chat(client)
    _send(client, chat_id, "  " + "x" * 100)
    assert db.get_chat(chat_id)["title"] == "x" * 60


def test_second_round_does_not_rename(client, monkeypatch):
    _script(monkeypatch, [_Result(), _Result()])
    chat_id = _new_chat(client)
    _send(client, chat_id, "erste")
    _send(client, chat_id, "zweite")
    assert db.get_chat(chat_id)["title"] == "erste"
