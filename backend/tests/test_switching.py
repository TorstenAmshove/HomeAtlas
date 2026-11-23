"""Shelly / Home Assistant switching: `switch_admin` against fake devices, the REST routes (role
gate, target checks, access log) and the `set_switch` assistant tool gaps not covered by
test_chat_owner_and_switch.py / test_switch_admin_cover.py."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, probe_auth, switch_admin, tools
from remote_helpers import access_actions, isolate_crypto


def _patch_httpx(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(switch_admin.httpx, "AsyncClient", factory)


# --- switch_admin against fake devices -----------------------------------------------------------

def _shelly(monkeypatch, gen, relay_status=200, identity=None):
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/shelly":
            if identity == "garbage":
                return httpx.Response(200, text="<html>nope</html>")
            return httpx.Response(200, json={"gen": gen} if gen else {})
        return httpx.Response(relay_status)

    _patch_httpx(monkeypatch, handler)
    return seen


@pytest.mark.parametrize("gen, on, expected", [
    (None, True, ("/relay/0", {"turn": "on"})),
    (1, False, ("/relay/0", {"turn": "off"})),
    (2, True, ("/rpc/Switch.Set", {"id": "0", "on": "true"})),
    (3, False, ("/rpc/Switch.Set", {"id": "0", "on": "false"})),
])
def test_shelly_generations(monkeypatch, gen, on, expected):
    seen = _shelly(monkeypatch, gen)
    assert asyncio.run(switch_admin.shelly_set_switch("10.0.0.7", on)) == {"ok": True, "error": ""}
    assert seen[-1] == expected


def test_shelly_channel_is_passed(monkeypatch):
    seen = _shelly(monkeypatch, 2)
    asyncio.run(switch_admin.shelly_set_switch("10.0.0.7", True, channel=3))
    assert seen[-1][1]["id"] == "3"


def test_shelly_http_error_and_non_shelly(monkeypatch):
    _shelly(monkeypatch, 2, relay_status=500)
    assert "HTTP 500" in asyncio.run(switch_admin.shelly_set_switch("10.0.0.7", True))["error"]
    _shelly(monkeypatch, 2, identity="garbage")
    result = asyncio.run(switch_admin.shelly_set_switch("10.0.0.7", True))
    assert result["ok"] is False and "Shelly" in result["error"]


def test_shelly_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("zu langsam")

    _patch_httpx(monkeypatch, handler)
    result = asyncio.run(switch_admin.shelly_set_switch("10.0.0.7", True))
    assert result["ok"] is False and "10.0.0.7" in result["error"]


def _ha(monkeypatch, status=200, fail=None):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers.get("authorization"),
                     json.loads(request.content or b"{}")))
        if fail:
            raise fail
        return httpx.Response(status, json=[])

    _patch_httpx(monkeypatch, handler)
    return seen


def test_ha_switch_success_sends_bearer_and_entity(monkeypatch):
    seen = _ha(monkeypatch)
    assert asyncio.run(switch_admin.ha_set_switch("http://ha:8123/", "tok", "light.k", False))["ok"]
    assert seen == [("POST", "/api/services/light/turn_off", "Bearer tok", {"entity_id": "light.k"})]


@pytest.mark.parametrize("entity", ["lock.haustuer", "climate.x", "alarm_control_panel.a", "cover.garage", ""])
def test_ha_switch_refuses_other_domains_without_request(monkeypatch, entity):
    seen = _ha(monkeypatch)
    result = asyncio.run(switch_admin.ha_set_switch("http://ha:8123", "tok", entity, True))
    assert result["ok"] is False and seen == []


def test_ha_switch_requires_url_and_token(monkeypatch):
    seen = _ha(monkeypatch)
    assert not asyncio.run(switch_admin.ha_set_switch("", "tok", "switch.a", True))["ok"]
    assert not asyncio.run(switch_admin.ha_set_switch("http://ha", "", "switch.a", True))["ok"]
    assert seen == []


@pytest.mark.parametrize("status", [401, 403, 500])
def test_ha_switch_http_errors_do_not_leak_the_token(monkeypatch, status):
    _ha(monkeypatch, status=status)
    result = asyncio.run(switch_admin.ha_set_switch("http://ha:8123", "geheim-token", "switch.a", True))
    assert result["ok"] is False and str(status) in result["error"] and "geheim-token" not in result["error"]


def test_ha_switch_unreachable(monkeypatch):
    _ha(monkeypatch, fail=httpx.ConnectError("refused"))
    result = asyncio.run(switch_admin.ha_set_switch("http://ha:8123", "geheim-token", "switch.a", True))
    assert result["ok"] is False and "nicht erreichbar" in result["error"] and "geheim-token" not in result["error"]


# --- REST routes ---------------------------------------------------------------------------------

class _Calls(list):
    outcome: dict


def _client(role: str) -> TestClient:
    user = {"id": "u1", "role": role, "username": role.lower(), "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    return TestClient(main.app)


@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    isolate_crypto(monkeypatch, tmp_path)
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture()
def shelly_calls(monkeypatch):
    calls = _Calls()
    outcome = {"ok": True, "error": ""}

    async def fake(host, on, channel=0):
        calls.append((host, on, channel))
        return dict(outcome)

    monkeypatch.setattr(switch_admin, "shelly_set_switch", fake)
    calls.outcome = outcome
    return calls


def _plug(**kw):
    return db.create_system({"name": "Steckdose", "kind": "iot", "ip": "10.0.0.7", "vendor": "Shelly", **kw})


@pytest.mark.parametrize("action, on", [("on", True), ("off", False)])
def test_shelly_route_admin_success(env, shelly_calls, action, on):
    plug = _plug()
    resp = _client(auth.ROLE_ADMIN).post(f"/api/systems/{plug['id']}/shelly-switch/{action}?channel=2")
    assert resp.status_code == 200 and shelly_calls == [("10.0.0.7", on, 2)]
    assert "switch.shelly" in access_actions()


def test_shelly_route_member_refused(env, shelly_calls):
    plug = _plug()
    assert _client(auth.ROLE_MEMBER).post(f"/api/systems/{plug['id']}/shelly-switch/on").status_code == 403
    assert shelly_calls == []


def test_shelly_route_rejections(env, shelly_calls):
    admin = _client(auth.ROLE_ADMIN)
    plug = _plug()
    assert admin.post(f"/api/systems/{plug['id']}/shelly-switch/toggle").status_code == 404
    assert admin.post("/api/systems/nope/shelly-switch/on").status_code == 404
    assert admin.post(f"/api/systems/{plug['id']}/shelly-switch/on?channel=9").status_code == 422
    nas = db.create_system({"name": "NAS", "kind": "nas", "ip": "10.0.0.2", "vendor": "Synology"})
    assert admin.post(f"/api/systems/{nas['id']}/shelly-switch/on").status_code == 400
    no_addr = db.create_system({"name": "x", "kind": "iot", "vendor": "Shelly"})
    assert admin.post(f"/api/systems/{no_addr['id']}/shelly-switch/on").status_code == 400
    assert shelly_calls == []


def test_shelly_route_device_error_is_400_and_logged(env, shelly_calls):
    shelly_calls.outcome.update(ok=False, error="offline")
    plug = _plug()
    resp = _client(auth.ROLE_ADMIN).post(f"/api/systems/{plug['id']}/shelly-switch/on")
    assert resp.status_code == 400 and resp.json()["detail"] == "offline"
    assert not next(e for e in db.list_access_log(10) if e["action"] == "switch.shelly")["ok"]


def _ha_setup(token="tok"):
    system = db.create_system({"name": "HA", "kind": "server", "ip": "10.0.0.3"})
    account = db.create_account({"systemId": system["id"], "category": "homeassistant",
                                 "url": "http://ha:8123", "secretEnc": crypto.encrypt(token)})
    return system, account


@pytest.fixture()
def ha_calls(monkeypatch):
    calls = _Calls()
    outcome = {"ok": True, "error": ""}

    async def fake(url, token, entity, on):
        calls.append((url, token, entity, on))
        return dict(outcome)

    monkeypatch.setattr(switch_admin, "ha_set_switch", fake)
    calls.outcome = outcome
    return calls


def _ha_url(system, account, action="on", entity="light.k"):
    return f"/api/systems/{system['id']}/ha-switch/{action}?accountId={account['id']}&entityId={entity}"


def test_ha_route_admin_success_and_log(env, ha_calls):
    system, account = _ha_setup()
    resp = _client(auth.ROLE_ADMIN).post(_ha_url(system, account, "off"))
    assert resp.status_code == 200 and ha_calls == [("http://ha:8123", "tok", "light.k", False)]
    assert "switch.ha" in access_actions()


def test_ha_route_member_refused(env, ha_calls):
    system, account = _ha_setup()
    assert _client(auth.ROLE_MEMBER).post(_ha_url(system, account)).status_code == 403
    assert _client(auth.ROLE_MEMBER).get(
        f"/api/systems/{system['id']}/ha-switchables?accountId={account['id']}").status_code == 403
    assert ha_calls == []


def test_ha_route_rejections(env, ha_calls):
    admin = _client(auth.ROLE_ADMIN)
    system, account = _ha_setup()
    other_system, other_account = _ha_setup()
    assert admin.post(_ha_url(system, account, "toggle")).status_code == 404
    assert admin.post(_ha_url(system, other_account)).status_code == 404  # account of another system
    assert admin.post(_ha_url(system, {"id": "nope"})).status_code == 404
    ssh = db.create_account({"systemId": system["id"], "category": "sshkey"})
    assert admin.post(_ha_url(system, ssh)).status_code == 404  # not a Home Assistant account
    assert other_system and ha_calls == []


def test_ha_route_unreadable_secret_is_409_and_logged(env, ha_calls, tmp_path, monkeypatch):
    system, account = _ha_setup()
    # A different key makes the stored secret undecryptable.
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "other.key")
    monkeypatch.setattr(crypto, "_cached", None)
    resp = _client(auth.ROLE_ADMIN).post(_ha_url(system, account))
    assert resp.status_code == 409 and ha_calls == []
    assert not next(e for e in db.list_access_log(10) if e["action"] == "switch.ha")["ok"]


def test_ha_route_device_error_is_400(env, ha_calls):
    ha_calls.outcome.update(ok=False, error="abgelehnt")
    system, account = _ha_setup()
    resp = _client(auth.ROLE_ADMIN).post(_ha_url(system, account))
    assert resp.status_code == 400 and resp.json()["detail"] == "abgelehnt"


def test_ha_switchables_route(env, monkeypatch):
    system, account = _ha_setup()
    seen = {}

    async def fake(url, acc):
        seen["url"] = url
        return {"ok": True, "entities": [{"entityId": "light.k"}]}

    monkeypatch.setattr(probe_auth, "list_ha_switchables", fake)
    admin = _client(auth.ROLE_ADMIN)
    resp = admin.get(f"/api/systems/{system['id']}/ha-switchables?accountId={account['id']}")
    assert resp.status_code == 200 and resp.json() == {"entities": [{"entityId": "light.k"}]}
    assert admin.get(f"/api/systems/{system['id']}/ha-switchables?accountId=nope").status_code == 404

    async def failing(url, acc):
        return {"ok": False, "error": "kaputt"}

    monkeypatch.setattr(probe_auth, "list_ha_switchables", failing)
    assert admin.get(f"/api/systems/{system['id']}/ha-switchables?accountId={account['id']}").status_code == 400


# --- set_switch tool: remaining gaps ----------------------------------------------------------------

def _tool(args):
    return json.loads(asyncio.run(tools.dispatch("set_switch", args)))


def test_set_switch_tool_input_gaps(env, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not switch")

    monkeypatch.setattr(switch_admin, "shelly_set_switch", boom)
    monkeypatch.setattr(switch_admin, "ha_set_switch", boom)
    monkeypatch.setattr(switch_admin, "ha_set_cover", boom)
    plug = _plug()
    assert "error" in _tool({"kind": "lock", "systemId": plug["id"], "on": True})
    assert "error" in _tool({"kind": "shelly", "systemId": plug["id"]})  # no `on`
    assert "error" in _tool({"kind": "shelly", "systemId": "nope", "on": True})
    no_addr = db.create_system({"name": "x", "kind": "iot", "vendor": "Shelly"})
    assert "error" in _tool({"kind": "shelly", "systemId": no_addr["id"], "on": True})


def test_set_switch_tool_ha_unknown_account_and_unreadable_secret(env, monkeypatch, tmp_path):
    async def boom(*a, **k):
        raise AssertionError("must not switch")

    monkeypatch.setattr(switch_admin, "ha_set_switch", boom)
    assert "error" in _tool({"kind": "ha", "accountId": "nope", "entityId": "light.k", "on": True})
    system, account = _ha_setup()
    db.update_account(account["id"], {"allowProbe": True})
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "other.key")
    monkeypatch.setattr(crypto, "_cached", None)
    assert _tool({"kind": "ha", "accountId": account["id"], "entityId": "light.k", "on": True}) == {
        "error": "Zugang nicht lesbar."}


@pytest.mark.parametrize("entity", ["lock.haustuer", "climate.x"])
def test_set_switch_tool_other_domains_never_reach_a_device(env, monkeypatch, entity):
    """Passes through to ha_set_switch, whose domain allowlist refuses before any HTTP request."""
    seen = _ha(monkeypatch)
    system, account = _ha_setup()
    db.update_account(account["id"], {"allowProbe": True})
    out = _tool({"kind": "ha", "accountId": account["id"], "entityId": entity, "on": True})
    assert "error" in out and seen == []


@pytest.mark.parametrize("device_class", ["garage", "gate", "door", "window", None])
def test_set_switch_tool_cover_classes_outside_allowlist_are_refused(env, monkeypatch, device_class):
    seen = []

    def handler(request):
        seen.append(request.method)
        attrs = {} if device_class is None else {"device_class": device_class}
        return httpx.Response(200, json={"attributes": attrs})

    _patch_httpx(monkeypatch, handler)
    system, account = _ha_setup()
    db.update_account(account["id"], {"allowProbe": True})
    out = _tool({"kind": "ha", "accountId": account["id"], "entityId": "cover.tor", "action": "open"})
    assert "error" in out and seen == ["GET"]  # state was read, nothing was moved
