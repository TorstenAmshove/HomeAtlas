"""proxmox_admin.guest_action -- the write-capable counterpart to proxmox_probe.list_guests'
read-only REST calls (see proxmox_admin.py's own module docstring for why this is a separate
module rather than a function added to proxmox_probe.py)."""
import asyncio

import httpx

from app import proxmox_admin


def _fake_client(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(proxmox_admin.httpx, "AsyncClient", _FakeAsyncClient)


def test_guest_action_posts_the_right_status_verb_for_each_action(monkeypatch):
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"data": "UPID:..."})

    _fake_client(monkeypatch, handler)

    for action, verb in (("start", "start"), ("stop", "shutdown"), ("restart", "reboot")):
        result = asyncio.run(proxmox_admin.guest_action(
            "https://pve.local:8006", "root@pam!token", "secret", "pve", "container", "101", action))
        assert result["ok"]
        assert seen_paths[-1] == f"/api2/json/nodes/pve/lxc/101/status/{verb}"

    # "stop" is Proxmox's graceful shutdown, never its hard power-cut endpoint.
    assert "/status/stop" not in seen_paths


def test_guest_action_uses_qemu_path_for_vms(monkeypatch):
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"data": "UPID:..."})

    _fake_client(monkeypatch, handler)

    asyncio.run(proxmox_admin.guest_action(
        "https://pve.local:8006", "root@pam!token", "secret", "pve", "vm", "202", "start"))

    assert seen_paths == ["/api2/json/nodes/pve/qemu/202/status/start"]


def test_guest_action_rejects_unknown_action():
    result = asyncio.run(proxmox_admin.guest_action(
        "https://pve.local:8006", "root@pam!token", "secret", "pve", "vm", "202", "delete"))
    assert not result["ok"]
    assert "Unbekannte Aktion" in result["error"]


def test_guest_action_requires_address():
    result = asyncio.run(proxmox_admin.guest_action("", "root@pam!token", "secret", "pve", "vm", "202", "start"))
    assert not result["ok"]
    assert "Adresse" in result["error"]


def test_guest_action_requires_token():
    result = asyncio.run(proxmox_admin.guest_action(
        "https://pve.local:8006", "", "", "pve", "vm", "202", "start"))
    assert not result["ok"]
    assert "Token" in result["error"]


def test_guest_action_reports_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": {"vmid": "no permission"}})

    _fake_client(monkeypatch, handler)

    result = asyncio.run(proxmox_admin.guest_action(
        "https://pve.local:8006", "root@pam!token", "secret", "pve", "vm", "202", "start"))

    assert not result["ok"]
    assert "fehlgeschlagen" in result["error"]


def test_guest_action_reports_unreachable_host(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _fake_client(monkeypatch, handler)

    result = asyncio.run(proxmox_admin.guest_action(
        "https://pve.local:8006", "root@pam!token", "secret", "pve", "vm", "202", "start"))

    assert not result["ok"]
    assert "nicht erreichbar" in result["error"]


import pytest  # noqa: E402


def _call(**overrides):
    args = {"base_url": "https://pve.local:8006", "token_id": "root@pam!t", "token_secret": "s",
            "node": "pve", "kind": "container", "vmid": "101", "action": "stop"}
    args.update(overrides)
    return asyncio.run(proxmox_admin.guest_action(**args))


@pytest.mark.parametrize("status,body,fallback", [
    (401, "", True), (403, "", True), (502, "", True), (503, "", True), (504, "", True),
    (400, "bad", False), (404, "", False), (409, "", False),
    (500, "VM already stopped", False), (500, "", False),
])
def test_guest_action_marks_fallback_only_for_connection_and_auth_errors(monkeypatch, status, body, fallback):
    _fake_client(monkeypatch, lambda request: httpx.Response(status, text=body))
    result = _call()
    assert not result["ok"]
    assert result["fallback"] is fallback


def test_guest_action_fallback_flags_for_other_outcomes(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    _fake_client(monkeypatch, boom)
    assert _call()["fallback"] is True
    assert _call(base_url="")["fallback"] is True
    assert _call(token_secret="")["fallback"] is True
    assert _call(action="nope")["fallback"] is False


def test_guest_action_success_is_no_fallback(monkeypatch):
    _fake_client(monkeypatch, lambda request: httpx.Response(200, json={}))
    ok = _call()
    assert ok["ok"] and ok["fallback"] is False
