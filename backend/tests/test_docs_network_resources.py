import asyncio

from app import db, docs


def test_network_documentation_includes_active_controller_resources(temp_db):
    account = db.create_account({"label": "UCG", "category": "unifi"})
    resources = db.sync_network_resources(account["id"], [
        {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "network",
         "externalId": "20", "name": "IoT", "facts": {"vlanId": 20, "cidr": "192.168.20.0/24"}},
        {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "wifi",
         "externalId": "wifi-1", "name": "Haus-IoT", "facts": {"security": "WPA2"}, "manualMd": "Nur Geräte"},
    ], [("default", "network"), ("default", "wifi")])
    db.update_network_resource_manual(resources[1]["id"], "Nur Geräte")

    asyncio.run(docs.generate(db.get_settings(), use_llm=False))

    body = db.get_doc_page("netzwerk")["bodyMd"]
    assert "## Vom Controller erfasste Netze" in body
    assert "| IoT | Haus | 20 | 192.168.20.0/24 | - |" in body
    assert "| Haus-IoT | Haus | WPA2 | - | Nur Geräte |" in body


def test_wifi_table_shows_network_name(temp_db):
    account = db.create_account({"label": "UCG", "category": "unifi"})
    db.sync_network_resources(account["id"], [
        {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "wifi",
         "externalId": "w1", "name": "A", "facts": {"security": "WPA2", "networkName": "I|oT"}},
        {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "wifi",
         "externalId": "w2", "name": "B", "facts": {"security": "WPA2"}},
    ], [("default", "wifi")])

    asyncio.run(docs.generate(db.get_settings(), use_llm=False))

    body = db.get_doc_page("netzwerk")["bodyMd"]
    assert "| Name | Standort | Sicherheit | Netz | Notiz |" in body
    assert "| A | Haus | WPA2 | I\\|oT | - |" in body
    assert "| B | Haus | WPA2 | - | - |" in body


def _vlan(external_id, name, vlan):
    return {"source": "unifi", "siteExternalId": "default", "siteName": "Haus", "kind": "network",
            "externalId": external_id, "name": name, "facts": {"vlanId": vlan, "cidr": f"10.0.{vlan}.0/24"}}


def test_docs_vlan_lists_ports(temp_db):
    account = db.create_account({"label": "UCG", "category": "unifi"})
    db.sync_network_resources(account["id"], [
        _vlan("a", "Default", 10), _vlan("b", "IoT", 20), _vlan("c", "IoT2", 20), _vlan("d", "Leer", 40),
    ], [("default", "network")])
    port = lambda n, vlan, mode, excluded=(): {  # noqa: E731
        "port": n, "name": "", "profile": "", "native": {"vlan": vlan, "name": "x", "known": True},
        "tagged": {"mode": mode, "vlans": [], "excluded": list(excluded)}}
    db.create_system({"name": "Switch Flur", "kind": "switch", "ip": "192.0.2.2", "extra": {"unifi": {"ports": {
        "accountId": account["id"], "site": "default",
        "ports": [port(1, 10, "all", [{"vlan": 40, "name": "Leer"}]), port(2, 20, "none")]}}}})

    asyncio.run(docs.generate(db.get_settings(), use_llm=False))

    body = db.get_doc_page("netzwerk")["bodyMd"]
    assert "| Name | Standort | VLAN | Netzwerk | Switchports | Notiz |" in body
    assert "| Default | Haus | 10 | 10.0.10.0/24 | nativ: Switch Flur 1 | - |" in body
    assert "| IoT | Haus | 20 | 10.0.20.0/24 | nativ: Switch Flur 2; tagged: Switch Flur 1 | - |" in body
    assert "| IoT2 | Haus | 20 | 10.0.20.0/24 | nativ: Switch Flur 2; tagged: Switch Flur 1 | - |" in body
    assert "| Leer | Haus | 40 | 10.0.40.0/24 | - | - |" in body


def test_docs_vlan_table_unchanged_without_port_data(temp_db):
    account = db.create_account({"label": "UCG", "category": "unifi"})
    db.sync_network_resources(account["id"], [_vlan("a", "Default", 10)], [("default", "network")])
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))
    assert "Switchports" not in db.get_doc_page("netzwerk")["bodyMd"]
