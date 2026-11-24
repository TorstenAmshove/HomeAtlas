"""#135: the manual "Auslesen" and the full scan read a device through the same code."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, pipeline, probe_auth, proxmox_probe


@pytest.fixture()
def client(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def _fake_outcome(ok=True, error=""):
    return {"ran": True, "purpose": "Router", "reason": "", "results": {
        "ssh:SSH": {"ok": ok, "error": error, "facts": {
            "os": {"label": "OS", "value": "OpenWrt 23\nzweite Zeile"},
            "model": {"label": "Modell", "value": "  RT-1  "},
        }},
    }}


def _router():
    system = db.create_system({"kind": "router", "name": "GW", "ip": "10.0.0.1"})
    db.create_account({"systemId": system["id"], "label": "SSH", "category": "sshkey", "allowProbe": 1})
    return system


def _snapshot(system_id):
    s = db.get_system(system_id)
    return (s["extra"]["probe"], s["purpose"], s["os"], s["model"],
            sorted(x["mac"] for x in db.list_systems() if x.get("mac")),
            [(e["level"], e["message"]) for e in db.list_device_error_events(system_id)])


def test_manual_and_full_scan_same_facts(client, monkeypatch):
    async def fake(system, accounts):
        out = _fake_outcome()
        out["results"]["ssh:SSH"]["arp"] = {}
        return out

    monkeypatch.setattr(probe_auth, "probe_system", fake)
    monkeypatch.setattr(probe_auth, "extract_arp_entries", lambda o: {"10.0.0.50": "aa:bb:cc:00:00:50"})

    async def no_dns(_ip):
        return ""

    monkeypatch.setattr(pipeline.discovery, "reverse_dns", no_dns)
    system = _router()
    assert client.post(f"/api/systems/{system['id']}/probe").status_code == 200
    manual = _snapshot(system["id"])
    assert manual[2] == "OpenWrt 23" and manual[3] == "RT-1"
    assert manual[4] == ["aa:bb:cc:00:00:50"]

    # Reset to the pre-probe state and run the full-scan step.
    db.update_system(system["id"], {"extra": {}, "purpose": "", "os": "", "model": ""})
    for s in db.list_systems():
        if s["id"] != system["id"]:
            db.delete_system(s["id"])
    probed, _w, arp = asyncio.run(pipeline._probe_with_credentials(lambda _l: None))
    asyncio.run(pipeline._learn_devices_from_arp(arp, lambda _l: None))
    assert probed == 1
    assert _snapshot(system["id"]) == manual


def test_probe_one_fills_os_model_only_when_empty(temp_db, monkeypatch):
    async def fake(system, accounts):
        out = _fake_outcome()
        out["results"]["ssh:SSH"]["facts"]["os"]["value"] = "x" * 300
        return out

    monkeypatch.setattr(probe_auth, "probe_system", fake)
    system = _router()
    db.update_system(system["id"], {"model": "Handgepflegt"})
    asyncio.run(pipeline.probe_one_system(db.get_system(system["id"]), db.get_settings()))
    after = db.get_system(system["id"])
    assert len(after["os"]) == 120
    assert after["model"] == "Handgepflegt"


def test_exception_becomes_warning_and_error_event(temp_db, monkeypatch):
    async def boom(system, accounts):
        raise RuntimeError("timeout")

    monkeypatch.setattr(probe_auth, "probe_system", boom)
    system = _router()
    out = asyncio.run(pipeline.probe_one_system(system, db.get_settings()))
    assert out["ran"] is False and "timeout" in out["reason"]
    assert any("timeout" in w for w in out["warnings"])
    assert db.list_device_error_events(system["id"])


def test_manual_respects_scan_use_credentials(client, monkeypatch):
    called = []

    async def fake(system, accounts):
        called.append(1)
        return _fake_outcome()

    monkeypatch.setattr(probe_auth, "probe_system", fake)
    system = _router()
    db.update_settings({"scanUseCredentials": False})
    body = client.post(f"/api/systems/{system['id']}/probe").json()
    assert body["outcome"]["ran"] is False
    assert "abgeschaltet" in body["outcome"]["reason"]
    assert not called


def test_manual_no_account_still_400(client):
    system = db.create_system({"kind": "router", "name": "GW", "ip": "10.0.0.1"})
    assert client.post(f"/api/systems/{system['id']}/probe").status_code == 400


def test_manual_uses_default_credential_with_port_check(client, monkeypatch):
    seen = []

    async def fake(system, accounts):
        seen.append(accounts)
        return _fake_outcome()

    monkeypatch.setattr(probe_auth, "probe_system", fake)
    db.update_settings({"defaultCredentialEnabled": True, "defaultCredentialSecretEnc": crypto.encrypt("pw")})
    closed = db.create_system({"kind": "server", "name": "A", "ip": "10.0.0.2", "openPorts": [80]})
    opened = db.create_system({"kind": "server", "name": "B", "ip": "10.0.0.3", "openPorts": [22]})
    assert client.post(f"/api/systems/{closed['id']}/probe").status_code == 400
    assert client.post(f"/api/systems/{opened['id']}/probe").json()["outcome"]["ran"] is True
    assert seen[0][0]["id"] == "__default__"


def _controller(category, **kw):
    system = db.create_system({"kind": "server", "name": "PVE", "ip": "10.0.0.5"})
    db.create_account({"systemId": system["id"], "label": "API", "category": category, "allowProbe": 1,
                       "url": "https://10.0.0.5", "username": "t@pve!x",
                       "secretEnc": crypto.encrypt("secret"), **kw})
    return system


def test_manual_proxmox_same_result_as_full_scan(client, monkeypatch):
    host = _controller("proxmox")

    async def fake(url, token_id, secret):
        return {"ok": True, "error": "", "systems": [
            {"discoveryKey": "pve:100", "kind": "vm", "name": "Gast", "discovered": 1,
             "discoverySource": "proxmox", "extra": {}}]}

    monkeypatch.setattr(proxmox_probe, "probe", fake)
    body = client.post(f"/api/systems/{host['id']}/probe").json()
    assert body["outcome"]["ran"] is True
    assert body["outcome"]["results"]["proxmox:API"]["ok"] is True
    guest = next(s for s in db.list_systems() if s["name"] == "Gast")
    assert guest["parentId"] == host["id"]


def test_manual_respects_scan_enable_proxmox(client, monkeypatch):
    host = _controller("proxmox")
    db.update_settings({"scanEnableProxmox": False})
    body = client.post(f"/api/systems/{host['id']}/probe").json()
    assert body["outcome"]["ran"] is False
    assert "Proxmox" in body["outcome"]["reason"]



def test_mixed_ssh_and_controller_partial_success(client, monkeypatch):
    async def fake(system, accounts):
        return _fake_outcome()

    async def bad(url, token_id, secret):
        return {"ok": False, "error": "Token abgelehnt", "systems": []}

    monkeypatch.setattr(probe_auth, "probe_system", fake)
    monkeypatch.setattr(proxmox_probe, "probe", bad)
    host = _controller("proxmox")
    db.create_account({"systemId": host["id"], "label": "SSH", "category": "sshkey", "allowProbe": 1})
    out = client.post(f"/api/systems/{host['id']}/probe").json()["outcome"]
    assert out["ran"] is True and out["reason"] == ""
    assert out["results"]["proxmox:API"]["ok"] is False
