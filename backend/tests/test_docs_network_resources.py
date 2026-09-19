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
    assert "| Haus-IoT | Haus | WPA2 | Nur Geräte |" in body
