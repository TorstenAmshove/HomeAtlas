"""#49: chats belong to their creator, admins see all. #43: `set_switch` names who switched
(chat user or MCP token) in the access log."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import auth, db, main, mcp_server, switch_admin, tools

ANNA = {"id": "u-anna", "role": auth.ROLE_MEMBER, "username": "anna", "totpEnabled": 1}
BERT = {"id": "u-bert", "role": auth.ROLE_MEMBER, "username": "bert", "totpEnabled": 1}
ADMIN = {"id": "u-admin", "role": auth.ROLE_ADMIN, "username": "admin", "totpEnabled": 1}


@pytest.fixture()
def as_user(temp_db):
    def _as(user: dict) -> TestClient:
        main.app.dependency_overrides[main.current_user] = lambda: user
        return TestClient(main.app)
    try:
        yield _as
    finally:
        main.app.dependency_overrides.clear()


# --- #49 --------------------------------------------------------------------------------------

def test_member_sees_only_own_chats(as_user):
    chat = as_user(ANNA).post("/api/chats").json()["chat"]
    assert chat["userId"] == "u-anna"
    assert [c["id"] for c in as_user(ANNA).get("/api/chats").json()["chats"]] == [chat["id"]]
    bert = as_user(BERT)  # replaces the override: from here on every request is Bert's
    assert bert.get("/api/chats").json()["chats"] == []
    assert bert.get(f"/api/chats/{chat['id']}/messages").status_code == 404
    assert bert.post(f"/api/chats/{chat['id']}/messages", json={"message": "hi"}).status_code == 404
    assert bert.delete(f"/api/chats/{chat['id']}").status_code == 404
    assert db.get_chat(chat["id"]) is not None


def test_admin_sees_all_including_ownerless(as_user):
    # One override is active at a time (as_user replaces it), so each block uses its own client.
    mine = as_user(ANNA).post("/api/chats").json()["chat"]
    legacy = db.create_chat("Alt")  # created before ownership existed
    assert as_user(ANNA).get(f"/api/chats/{legacy['id']}/messages").status_code == 404
    admin = as_user(ADMIN)
    ids = {c["id"] for c in admin.get("/api/chats").json()["chats"]}
    assert {mine["id"], legacy["id"]} <= ids
    assert admin.get(f"/api/chats/{mine['id']}/messages").status_code == 200
    assert admin.delete(f"/api/chats/{legacy['id']}").status_code == 200


def test_owner_can_delete(as_user):
    chat = as_user(ANNA).post("/api/chats").json()["chat"]
    assert as_user(ANNA).delete(f"/api/chats/{chat['id']}").status_code == 200
    assert db.get_chat(chat["id"]) is None


# --- #43 --------------------------------------------------------------------------------------

def test_mcp_middleware_sets_token_as_actor(temp_db):
    token = db.create_api_token("Laptop")["token"]
    seen = {}

    async def inner(scope, receive, send):
        seen["actor"] = tools.current_actor.get()

    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
    asyncio.run(mcp_server._BearerAuth(inner)(scope, None, None))
    assert seen["actor"] == {"username": "MCP: Laptop"}
    assert tools.current_actor.get() is None


def test_set_switch_logs_chat_user(temp_db, monkeypatch):
    account = _ha_account(temp_db)

    async def fake_set(url, token, entity, on):
        return {"ok": True, "error": ""}

    monkeypatch.setattr(switch_admin, "ha_set_switch", fake_set)
    token = tools.current_actor.set({"user": {"id": "u-anna", "username": "anna"}})
    try:
        out = json.loads(asyncio.run(tools.dispatch(
            "set_switch", {"kind": "ha", "accountId": account["id"], "entityId": "light.stehlampe", "on": True})))
    finally:
        tools.current_actor.reset(token)
    assert out["ok"] is True
    entry = db.list_access_log(5, "switch.assistant")[0]
    assert entry["username"] == "anna" and "light.stehlampe" in entry["detail"]


# --- #99 PR3: shutters via set_switch ---------------------------------------------------------

def _ha_account(temp_db, allow_probe=True):
    return db.create_account({"label": "HA", "category": "homeassistant", "url": "http://ha:8123",
                              "allowProbe": 1 if allow_probe else 0})


def _ha_call(args: dict) -> dict:
    return json.loads(asyncio.run(tools.dispatch("set_switch", {"kind": "ha", **args})))


def test_set_switch_cover_via_tool(temp_db, monkeypatch):
    acc = _ha_account(temp_db)
    seen = {}

    async def fake(url, token, entity, action):
        seen["a"] = (entity, action)
        return {"ok": True, "error": ""}

    monkeypatch.setattr(switch_admin, "ha_set_cover", fake)
    out = _ha_call({"accountId": acc["id"], "entityId": "cover.buero", "action": "close"})
    assert out["ok"] is True and seen["a"] == ("cover.buero", "close")
    assert any(e["action"] == "switch.assistant" for e in db.list_access_log(10))


def test_set_switch_on_for_cover_rejected(temp_db):
    acc = _ha_account(temp_db)
    assert "error" in _ha_call({"accountId": acc["id"], "entityId": "cover.buero", "on": True})


def test_set_switch_action_for_light_rejected(temp_db):
    acc = _ha_account(temp_db)
    assert "error" in _ha_call({"accountId": acc["id"], "entityId": "light.x", "action": "open"})
    assert "error" in _ha_call({"accountId": acc["id"], "entityId": "light.x"})


@pytest.mark.parametrize("allow", [0, None])
def test_set_switch_ha_requires_opt_in(temp_db, monkeypatch, allow):
    acc = _ha_account(temp_db, allow_probe=False)
    if allow is None:
        db.update_account(acc["id"], {"allowProbe": None})

    async def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(switch_admin, "ha_set_cover", boom)
    monkeypatch.setattr(switch_admin, "ha_set_switch", boom)
    for args in ({"entityId": "cover.x", "action": "open"}, {"entityId": "light.x", "on": True}):
        out = _ha_call({"accountId": acc["id"], **args})
        assert "Zum Auslesen verwenden" in out["error"]
    assert not any(e["action"] == "switch.assistant" for e in db.list_access_log(10))
