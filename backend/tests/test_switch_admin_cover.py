"""#99 PR3: `ha_set_cover` only moves shutter-like covers (device_class allowlist), never garage/gate/door."""
import asyncio

import httpx
import pytest

from app import probe_auth, switch_admin


def _run(entity_id: str, action: str, device_class, state_status: int = 200, entity_present: bool = True):
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            if state_status != 200:
                return httpx.Response(state_status)
            attrs = {} if device_class is None else {"device_class": device_class}
            return httpx.Response(200, json={"entity_id": entity_id, "state": "open", "attributes": attrs})
        return httpx.Response(200, json=[])

    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    return calls, factory


def _call(monkeypatch, entity_id, action, device_class, **kw):
    calls, factory = _run(entity_id, action, device_class, **kw)
    monkeypatch.setattr(switch_admin.httpx, "AsyncClient", factory)
    result = asyncio.run(switch_admin.ha_set_cover("http://ha:8123", "tok", entity_id, action))
    return result, calls


@pytest.mark.parametrize("dc", ["shutter", "blind", "shade", "curtain", "awning", "window", "Shutter "])
def test_cover_matrix_allowed(monkeypatch, dc):
    result, calls = _call(monkeypatch, "cover.buero", "close", dc)
    assert result["ok"] is True
    assert ("POST", "/api/services/cover/close_cover") in calls


@pytest.mark.parametrize("dc", ["garage", "gate", "door", None, "", "damper"])
def test_cover_matrix_rejected(monkeypatch, dc):
    result, calls = _call(monkeypatch, "cover.tor", "open", dc)
    assert result["ok"] is False
    assert not any(m == "POST" for m, _ in calls)


@pytest.mark.parametrize("entity", ["lock.haustuer", "climate.bad", "alarm_control_panel.home", "switch.x"])
def test_other_domains_rejected(monkeypatch, entity):
    result, calls = _call(monkeypatch, entity, "open", "shutter")
    assert result["ok"] is False
    assert calls == []


@pytest.mark.parametrize("action", ["toggle", "set_position", "", "OPEN"])
def test_bad_action(monkeypatch, action):
    result, calls = _call(monkeypatch, "cover.buero", action, "shutter")
    assert result["ok"] is False
    assert calls == []


def test_bad_entity_id(monkeypatch):
    result, calls = _call(monkeypatch, "cover.buero/../../x", "open", "shutter")
    assert result["ok"] is False
    assert calls == []


def test_entity_missing_or_get_fails(monkeypatch):
    for status in (404, 500):
        result, calls = _call(monkeypatch, "cover.buero", "open", "shutter", state_status=status)
        assert result["ok"] is False
        assert not any(m == "POST" for m, _ in calls)


def test_ha_set_switch_still_refuses_cover():
    result = asyncio.run(switch_admin.ha_set_switch("http://ha:8123", "tok", "cover.buero", True))
    assert result["ok"] is False


def test_allowlists_in_sync():
    assert switch_admin._COVER_ALLOWED_CLASSES == probe_auth._HA_COVER_ALLOWED_CLASSES
