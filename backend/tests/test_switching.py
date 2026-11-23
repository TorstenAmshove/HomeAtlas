"""Home Assistant switching: `switch_admin` against fake devices and the `set_switch` assistant tool gaps not covered by
test_chat_owner_and_switch.py / test_switch_admin_cover.py."""
import asyncio
import json

import httpx
import pytest

from app import crypto, db, main, probe_auth, switch_admin, tools
from remote_helpers import isolate_crypto


def _patch_httpx(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(switch_admin.httpx, "AsyncClient", factory)


# --- switch_admin against fake devices -----------------------------------------------------------

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


# --- fixtures --------------------------------------------------------------------------------------

@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    isolate_crypto(monkeypatch, tmp_path)
    yield
    main.app.dependency_overrides.clear()


def _ha_setup(token="tok"):
    system = db.create_system({"name": "HA", "kind": "server", "ip": "10.0.0.3"})
    account = db.create_account({"systemId": system["id"], "category": "homeassistant",
                                 "url": "http://ha:8123", "secretEnc": crypto.encrypt(token)})
    return system, account


# --- set_switch tool: remaining gaps ----------------------------------------------------------------

def _tool(args):
    return json.loads(asyncio.run(tools.dispatch("set_switch", args)))


def test_set_switch_tool_input_gaps(env, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not switch")

    monkeypatch.setattr(switch_admin, "ha_set_switch", boom)
    monkeypatch.setattr(switch_admin, "ha_set_cover", boom)
    assert "error" in _tool({"kind": "lock", "systemId": "x", "on": True})


def test_set_switch_shelly_rejected(env, monkeypatch):
    """Shelly relays are no longer switched directly (ADR-0023), even for a Shelly in the inventory."""
    async def boom(*a, **k):
        raise AssertionError("must not switch")

    monkeypatch.setattr(switch_admin, "ha_set_switch", boom)
    assert not hasattr(switch_admin, "shelly_set_switch")
    plug = db.create_system({"name": "Steckdose", "kind": "iot", "ip": "10.0.0.7", "vendor": "Shelly"})
    out = _tool({"kind": "shelly", "systemId": plug["id"], "on": True})
    assert "error" in out and "'ha'" in out["error"]


def test_list_switches_has_no_shellies(env, monkeypatch):
    db.create_system({"name": "Steckdose", "kind": "iot", "ip": "10.0.0.7", "vendor": "Shelly"})
    system, account = _ha_setup()
    db.update_account(account["id"], {"allowProbe": True})

    async def fake(url, acc):
        return {"ok": True, "entities": [{"entityId": "light.k"}, {"entityId": "cover.r"}]}

    monkeypatch.setattr(probe_auth, "list_ha_switchables", fake)
    out = json.loads(asyncio.run(tools.dispatch("list_switches", {})))
    assert "shellies" not in out and "shellyCount" not in out
    assert out["haEntityCount"] == 2


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
