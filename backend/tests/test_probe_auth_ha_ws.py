"""Home Assistant automation traces over the WebSocket API: only trace/list and trace/get may be
sent, results are redacted and bounded, nothing raises."""
import asyncio
import json

import pytest
import websockets

from app import probe_auth

TOKEN = "fake-token-123"


def _run(coro):
    return asyncio.run(coro)


async def _serve(handler):
    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


def _handler(results: dict, seen: list, auth_ok: bool = True):
    async def handle(ws):
        await ws.send(json.dumps({"type": "auth_required"}))
        auth = json.loads(await ws.recv())
        seen.append(auth)
        if not auth_ok:
            await ws.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token"}))
            return
        await ws.send(json.dumps({"type": "auth_ok"}))
        async for raw in ws:
            msg = json.loads(raw)
            seen.append(msg)
            await ws.send(json.dumps({"id": msg["id"], "type": "result", "success": True,
                                      "result": results.get(msg["type"])}))
    return handle


def _with_server(monkeypatch, handler, coro_factory):
    monkeypatch.setattr(probe_auth, "_decode_secret", lambda account: (TOKEN, ""))

    async def main():
        server, url = await _serve(handler)
        try:
            return await coro_factory(url)
        finally:
            server.close()
            await server.wait_closed()
    return _run(main())


def test_handshake_and_trace_list(monkeypatch):
    seen: list = []
    runs = [{"run_id": "r1", "timestamp": {"start": "2026-01-01T10:00:00+00:00", "finish": "x"},
             "state": "stopped", "trigger": "state of binary_sensor.motion", "item_id": "abc"}]
    result = _with_server(monkeypatch, _handler({"trace/list": runs}, seen),
                          lambda url: probe_auth._ha_ws_call(url, {}, "trace/list", {"domain": "automation", "item_id": "abc"}))
    assert result["ok"] is True and result["data"] == runs
    assert seen[0] == {"type": "auth", "access_token": TOKEN}
    assert seen[1]["type"] == "trace/list" and seen[1]["item_id"] == "abc"


@pytest.mark.parametrize("bad", ["trace/list ", "TRACE/LIST", "call_service", "config/auth/list", 5, None])
def test_disallowed_type_rejected(monkeypatch, bad):
    monkeypatch.setattr(probe_auth, "_decode_secret", lambda account: (TOKEN, ""))
    with pytest.raises(ValueError):
        _run(probe_auth._ha_ws_call("http://127.0.0.1:1", {}, bad, {}))


def test_auth_invalid_message_without_token(monkeypatch):
    seen: list = []
    result = _with_server(monkeypatch, _handler({}, seen, auth_ok=False),
                          lambda url: probe_auth._ha_ws_call(url, {}, "trace/list", {}))
    assert result["ok"] is False
    assert TOKEN not in json.dumps(result)


def test_timeout_and_dropped_connection(monkeypatch):
    async def silent(ws):
        await ws.send(json.dumps({"type": "auth_required"}))
        await asyncio.sleep(5)

    async def drop(ws):
        await ws.close()

    monkeypatch.setattr(probe_auth, "_HA_WS_TIMEOUT", 0.3)
    for handler in (silent, drop):
        result = _with_server(monkeypatch, handler,
                              lambda url: probe_auth._ha_ws_call(url, {}, "trace/list", {}))
        assert result["ok"] is False and result["error"]
    # nothing listening
    monkeypatch.setattr(probe_auth, "_decode_secret", lambda account: (TOKEN, ""))
    assert _run(probe_auth._ha_ws_call("http://127.0.0.1:1", {}, "trace/list", {}))["ok"] is False


def test_ws_url_from_http_https_and_path_prefix():
    assert probe_auth._ha_ws_url("http://ha.local:8123") == "ws://ha.local:8123/api/websocket"
    assert probe_auth._ha_ws_url("https://ha.local/") == "wss://ha.local/api/websocket"
    assert probe_auth._ha_ws_url("http://proxy/ha") == "ws://proxy/ha/api/websocket"


def test_trace_without_id_attribute(monkeypatch):
    async def fake_get(url, account, path, params=None, *, as_text=False):
        return {"ok": True, "data": {"entity_id": "automation.yaml_one", "attributes": {}}}
    monkeypatch.setattr(probe_auth, "_ha_get", fake_get)
    result = _run(probe_auth.ha_traces("http://x", {}, "automation.yaml_one"))
    assert result["ok"] is False and "id" in result["error"].lower()


def test_entity_must_be_automation_or_script(monkeypatch):
    result = _run(probe_auth.ha_traces("http://x", {}, "light.kitchen"))
    assert result["ok"] is False


def test_trace_redacted_and_truncated(monkeypatch):
    seen: list = []
    runs = [{"run_id": f"r{i}", "timestamp": {"start": f"2026-01-01T10:{i:02d}:00+00:00"},
             "state": "stopped", "trigger": "x"} for i in range(15)]
    detail = {"trigger": "state password=hunter2", "error": "boom http://u:pw@h/x?token=abc",
              "trace": {"trigger/0": [{"result": {"x": "y" * 30000}}]}, "config": {}}

    async def fake_get(url, account, path, params=None, *, as_text=False):
        return {"ok": True, "data": {"entity_id": "automation.a", "attributes": {"id": "abc"}}}
    monkeypatch.setattr(probe_auth, "_ha_get", fake_get)
    handler = _handler({"trace/list": runs, "trace/get": detail}, seen)
    listed = _with_server(monkeypatch, handler,
                          lambda url: probe_auth.ha_traces(url, {}, "automation.a"))
    assert listed["ok"] and len(listed["runs"]) == 10 and listed["truncated"] and listed["note"]
    assert listed["runs"][0]["run_id"] == "r14"  # newest first
    got = _with_server(monkeypatch, handler,
                       lambda url: probe_auth.ha_traces(url, {}, "automation.a", "r1"))
    text = json.dumps(got)
    assert got["ok"] and "hunter2" not in text and "pw@" not in text and "abc" not in text.replace('"abc"', "")
    assert got["truncated"] and len(text) < 20000
