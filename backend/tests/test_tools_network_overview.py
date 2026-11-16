"""network_overview / chat state block report the networks a scan really covers."""
import asyncio
import json

from app import db, discovery, prompts, tools

ALLOWED_KEYS = {"cidr", "source", "name", "vlan"}


def _setup(monkeypatch, selected=(), free=(), active=True):
    monkeypatch.setattr(discovery, "local_subnets", lambda: (_ for _ in ()).throw(AssertionError("no subprocess")))
    account = db.create_account({"label": "UCG", "category": "unifi"})
    resources = db.sync_network_resources(account["id"], [
        {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "network",
         "externalId": "20", "name": "IoT", "facts": {"vlanId": 20, "cidr": "192.168.20.0/24"}},
    ], [("default", "network")])
    ids = [resources[0]["id"]] if selected else []
    if selected == "stale":
        ids = ["gone"]
    db.update_settings({"scanControllerNetworkIds": ids, "scanSubnets": list(free)})
    return resources


def _overview() -> dict:
    return json.loads(asyncio.run(tools.dispatch("network_overview", {})))


def test_overview_controller_only(temp_db, monkeypatch):
    _setup(monkeypatch, selected=True)
    data = _overview()
    assert data["configuredSubnets"] == ["192.168.20.0/24"]
    assert data["subnetSources"] == [
        {"cidr": "192.168.20.0/24", "source": "controller", "name": "IoT", "vlan": 20}]


def test_overview_free_text_only(temp_db, monkeypatch):
    _setup(monkeypatch, free=["10.0.0.0/24"])
    data = _overview()
    assert data["configuredSubnets"] == ["10.0.0.0/24"]
    assert data["subnetSources"] == [{"cidr": "10.0.0.0/24", "source": "freitext"}]


def test_overview_empty_is_automatic(temp_db, monkeypatch):
    _setup(monkeypatch)
    data = _overview()
    assert data["configuredSubnets"] == "automatisch erkannt"
    assert data["subnetSources"] == []


def test_overview_mixed_and_keys(temp_db, monkeypatch):
    _setup(monkeypatch, selected=True, free=["10.0.0.0/24"])
    data = _overview()
    assert data["configuredSubnets"] == ["192.168.20.0/24", "10.0.0.0/24"]
    assert all(set(e) <= ALLOWED_KEYS for e in data["subnetSources"])


def test_overview_stale_id_is_automatic(temp_db, monkeypatch):
    _setup(monkeypatch, selected="stale")
    assert _overview()["configuredSubnets"] == "automatisch erkannt"


def test_overview_inactive_network_is_automatic(temp_db, monkeypatch):
    resources = _setup(monkeypatch, selected=True)
    # a complete controller listing without the network marks it inactive
    db.sync_network_resources(db.get_network_resource(resources[0]["id"])["sourceAccountId"], [],
                              [("default", "network")])
    assert _overview()["configuredSubnets"] == "automatisch erkannt"


def test_state_block(temp_db, monkeypatch):
    _setup(monkeypatch, selected=True, free=["10.0.0.0/24"])
    assert "192.168.20.0/24, 10.0.0.0/24" in tools._state_block(db.get_settings())
    db.update_settings({"scanControllerNetworkIds": [], "scanSubnets": []})
    assert "automatisch erkannt" in tools._state_block(db.get_settings())
    assert prompts.CHAT_STATE_TEMPLATE  # real template is used by _state_block
