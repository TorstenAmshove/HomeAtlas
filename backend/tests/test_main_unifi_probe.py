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

    async def fake_probe(url, api_key, account_id, system_id):
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

    async def fake_probe(*_args):
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
