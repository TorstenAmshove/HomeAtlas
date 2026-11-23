"""main._proxmox_account is the single signal that routes list_remote_containers (and its action/
console counterparts) away from the Docker path for a Proxmox host -- see remote_admin.py's
list_remote_proxmox_guests and proxmox_probe.list_guests for what that routing avoids
("bash: line 1: docker: command not found")."""
from app import main


def test_proxmox_account_found_when_attached_to_system(temp_db):
    system = temp_db.create_system({"kind": "server", "name": "PVE-Host", "ip": "10.0.0.30"})
    temp_db.create_account({
        "systemId": system["id"], "label": "Proxmox API", "category": "proxmox",
        "username": "root@pam!homeatlas", "url": "https://10.0.0.30:8006",
    })

    account = main._proxmox_account(system["id"])

    assert account is not None
    assert account["category"] == "proxmox"


def test_proxmox_account_none_for_a_plain_docker_host(temp_db):
    system = temp_db.create_system({"kind": "server", "name": "NAS", "ip": "10.0.0.31"})
    temp_db.create_account({
        "systemId": system["id"], "label": "SSH", "category": "sshkey",
    })

    assert main._proxmox_account(system["id"]) is None


def test_proxmox_account_ignores_accounts_on_other_systems(temp_db):
    proxmox_host = temp_db.create_system({"kind": "server", "name": "PVE-Host", "ip": "10.0.0.32"})
    other_host = temp_db.create_system({"kind": "server", "name": "NAS", "ip": "10.0.0.33"})
    temp_db.create_account({
        "systemId": proxmox_host["id"], "label": "Proxmox API", "category": "proxmox",
        "username": "root@pam!homeatlas", "url": "https://10.0.0.32:8006",
    })

    assert main._proxmox_account(other_host["id"]) is None


# --- remote_container_action: SSH fallback only when the API is unusable --------------------

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import crypto, proxmox_admin, remote_admin  # noqa: E402
from app.routes import remote as remote_routes  # noqa: E402


def _setup_proxmox(temp_db, monkeypatch, api_result):
    system = temp_db.create_system({"kind": "server", "name": "PVE", "ip": "10.0.0.30"})
    temp_db.create_account({"systemId": system["id"], "label": "API", "category": "proxmox",
                            "username": "root@pam!h", "url": "https://10.0.0.30:8006"})
    ssh = temp_db.create_account({"systemId": system["id"], "label": "SSH", "category": "sshkey"})
    calls = {"api": 0, "ssh": 0}

    async def fake_api(*args):
        calls["api"] += 1
        return api_result

    async def fake_ssh(*args, **kwargs):
        calls["ssh"] += 1
        return {"ok": True, "error": ""}

    monkeypatch.setattr(proxmox_admin, "guest_action", fake_api)
    monkeypatch.setattr(remote_admin, "run_remote_proxmox_guest_command", fake_ssh)
    monkeypatch.setattr(crypto, "decrypt", lambda value: "")
    return system, ssh, calls


def _act(system, ssh, container_id="pve:lxc:101"):
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    return asyncio.run(remote_routes.remote_container_action(
        system["id"], container_id, "stop", ssh["id"], request, user={"id": "u"}))


def test_remote_container_action_no_ssh_fallback_on_functional_api_error(temp_db, monkeypatch):
    system, ssh, calls = _setup_proxmox(temp_db, monkeypatch, {
        "ok": False, "error": "Proxmox-Aktion fehlgeschlagen: already stopped", "fallback": False})
    with pytest.raises(HTTPException) as exc:
        _act(system, ssh)
    assert exc.value.status_code == 400
    assert "already stopped" in exc.value.detail
    assert calls["ssh"] == 0
    entry = temp_db.list_access_log(limit=1)[0]
    assert entry["action"] == "container.proxmox.stop"
    assert not entry["ok"]


def test_remote_container_action_falls_back_to_ssh_on_connection_error(temp_db, monkeypatch):
    system, ssh, calls = _setup_proxmox(temp_db, monkeypatch, {
        "ok": False, "error": "Proxmox-Host nicht erreichbar", "fallback": True})
    assert _act(system, ssh) == {"ok": True}
    assert calls["ssh"] == 1


def test_remote_container_action_unknown_node_uses_ssh(temp_db, monkeypatch):
    system, ssh, calls = _setup_proxmox(temp_db, monkeypatch, None)
    assert _act(system, ssh, "lxc:101") == {"ok": True}
    assert calls == {"api": 0, "ssh": 1}


def _unreadable(value):
    raise crypto.SecretUnreadable()


def test_remote_container_action_unreadable_token_without_ssh_is_409_and_logged(temp_db, monkeypatch):
    system, _ssh, calls = _setup_proxmox(temp_db, monkeypatch, {"ok": True, "error": "", "fallback": False})
    monkeypatch.setattr(crypto, "decrypt_strict", _unreadable)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(remote_routes.remote_container_action(
            system["id"], "pve:lxc:101", "stop", "", request, user={"id": "u"}))
    assert exc.value.status_code == 409
    assert calls == {"api": 0, "ssh": 0}
    entry = next(e for e in temp_db.list_access_log() if e["action"] == "container.proxmox.stop")
    assert not entry["ok"]


def test_remote_container_action_unreadable_token_falls_back_to_ssh(temp_db, monkeypatch):
    system, ssh, calls = _setup_proxmox(temp_db, monkeypatch, {"ok": True, "error": "", "fallback": False})
    monkeypatch.setattr(crypto, "decrypt_strict", _unreadable)
    assert _act(system, ssh) == {"ok": True}
    assert calls == {"api": 0, "ssh": 1}
