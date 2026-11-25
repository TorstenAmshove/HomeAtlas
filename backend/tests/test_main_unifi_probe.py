"""Manual UniFi controller synchronization through the device-detail action."""
import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, unifi_probe


@pytest.fixture()
def client(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_manual_unifi_probe_syncs_devices_topology_and_network_resources(client, monkeypatch):
    controller = db.create_system({
        "kind": "router", "name": "UCG", "ip": "192.168.42.2",
        "extra": {"unifi": {"deviceId": "gateway"}},
    })
    account = db.create_account({
        "systemId": controller["id"], "label": "UCG API", "category": "unifi", "allowProbe": 1,
        "url": "https://192.168.42.2", "secretEnc": crypto.encrypt("api-token"),
    })

    async def fake_probe(url, api_key, account_id, system_id, client_subnets=None):
        assert (url, api_key, account_id, system_id) == (
            "https://192.168.42.2", "api-token", account["id"], controller["id"],
        )
        return {
            "ok": True, "error": "", "warnings": [],
            "systems": [{
                "discoveryKey": "mac:aa:bb:cc:dd:ee:01", "kind": "network", "name": "Wohnzimmer-Switch",
                "ip": "192.168.42.3", "mac": "aa:bb:cc:dd:ee:01", "discovered": 1,
                "discoverySource": "unifi", "extra": {"unifi": {"deviceId": "switch", "uplinkDeviceId": "gateway"}},
            }],
            "resources": [{
                "source": "unifi", "siteExternalId": "default", "siteName": "Zuhause", "kind": "network",
                "externalId": "vlan-20", "name": "IoT", "ownerSystemId": controller["id"],
                "facts": {"vlanId": 20, "cidr": "192.168.20.0/24"},
            }],
            "completeScopes": [("default", "network")],
        }

    monkeypatch.setattr(unifi_probe, "probe", fake_probe)

    response = client.post(f"/api/systems/{controller['id']}/probe")

    assert response.status_code == 200
    assert response.json()["outcome"]["ran"] is True
    assert response.json()["outcome"]["results"]["unifi:UCG API"]["ok"] is True
    switch = next(system for system in db.list_systems() if system["name"] == "Wohnzimmer-Switch")
    assert switch["parentId"] == controller["id"]
    assert db.list_network_resources(active_only=True)[0]["name"] == "IoT"


def test_manual_unifi_probe_returns_the_controller_error(client, monkeypatch):
    controller = db.create_system({"kind": "router", "name": "UCG", "ip": "192.168.42.2"})
    db.create_account({
        "systemId": controller["id"], "label": "UCG API", "category": "unifi", "allowProbe": 1,
        "url": "https://192.168.42.2", "secretEnc": crypto.encrypt("api-token"),
    })

    async def fake_probe(*_args, **_kwargs):
        return {"ok": False, "error": "Der UniFi API-Key wurde abgelehnt.", "warnings": [],
                "systems": [], "resources": [], "completeScopes": []}

    monkeypatch.setattr(unifi_probe, "probe", fake_probe)

    response = client.post(f"/api/systems/{controller['id']}/probe")

    assert response.status_code == 200
    assert response.json()["outcome"] == {
        "ran": False,
        "results": {"unifi:UCG API": {"ok": False, "error": "Der UniFi API-Key wurde abgelehnt.", "facts": {}}},
        "purpose": "",
        "reason": "Der UniFi API-Key wurde abgelehnt.",
    }


def _setup_account():
    controller = db.create_system({"kind": "router", "name": "UCG", "ip": "192.168.42.2"})
    db.create_account({
        "systemId": controller["id"], "label": "UCG API", "category": "unifi", "allowProbe": 1,
        "url": "https://192.168.42.2", "secretEnc": crypto.encrypt("api-token"),
    })
    return controller


def _capture(monkeypatch, systems=()):
    seen = {}

    async def fake_probe(url, api_key, account_id, system_id, client_subnets=None):
        seen["subnets"] = client_subnets
        return {"ok": True, "error": "", "warnings": [], "systems": list(systems), "resources": [],
                "completeScopes": []}

    monkeypatch.setattr(unifi_probe, "probe", fake_probe)
    return seen


def test_manual_probe_passes_scan_subnets(client, monkeypatch):
    controller = _setup_account()
    seen = _capture(monkeypatch)
    db.update_settings({"scanSubnets": ["10.9.0.0/24"]})
    assert client.post(f"/api/systems/{controller['id']}/probe").status_code == 200
    assert "10.9.0.0/24" in seen["subnets"]


def test_manual_probe_falls_back_to_host_subnets(client, monkeypatch):
    from app import discovery
    controller = _setup_account()
    seen = _capture(monkeypatch)
    monkeypatch.setattr(discovery, "local_subnets", lambda: ["172.30.0.0/24"])
    assert client.post(f"/api/systems/{controller['id']}/probe").status_code == 200
    assert seen["subnets"] == ["172.30.0.0/24"]


def test_filtered_client_does_not_delete_existing_system(client, monkeypatch):
    controller = _setup_account()
    guest = db.create_system({"kind": "other", "name": "Gast", "ip": "192.168.50.5"})
    _capture(monkeypatch)
    assert client.post(f"/api/systems/{controller['id']}/probe").status_code == 200
    assert db.get_system(guest["id"])["name"] == "Gast"


def test_manual_probe_twice_with_empty_scope_keeps_resources_active(client, monkeypatch):
    controller = db.create_system({"kind": "router", "name": "UCG", "ip": "192.168.42.2"})
    db.create_account({
        "systemId": controller["id"], "label": "UCG API", "category": "unifi", "allowProbe": 1,
        "url": "https://192.168.42.2", "secretEnc": crypto.encrypt("api-token"),
    })
    resource = {
        "source": "unifi", "siteExternalId": "default", "siteName": "Zuhause", "kind": "network",
        "externalId": "vlan-20", "name": "IoT", "ownerSystemId": controller["id"],
        "facts": {"vlanId": 20, "cidr": "192.168.20.0/24"},
    }
    answers = [[resource], [], []]

    async def fake_probe(*_args, **_kwargs):
        return {"ok": True, "error": "", "warnings": [], "systems": [],
                "resources": answers.pop(0), "completeScopes": [("default", "network")]}

    monkeypatch.setattr(unifi_probe, "probe", fake_probe)

    for _ in range(3):
        assert client.post(f"/api/systems/{controller['id']}/probe").status_code == 200

    assert [r["name"] for r in db.list_network_resources(active_only=True)] == ["IoT"]
