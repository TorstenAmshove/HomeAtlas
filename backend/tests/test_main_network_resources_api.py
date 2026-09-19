"""HTTP-level coverage for the controller-synced network resource routes."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER}
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_network_resources_are_readable_by_members_and_manual_notes_require_an_admin(client):
    account = db.create_account({"label": "UCG", "category": "unifi"})
    resource = db.sync_network_resources(account["id"], [{
        "source": "unifi", "siteExternalId": "site-1", "siteName": "Haus", "kind": "network",
        "externalId": "vlan-20", "name": "IoT", "facts": {"vlanId": 20},
    }], [("site-1", "network")])[0]

    listing = client.get("/api/network-resources?kind=network&activeOnly=true")

    assert listing.status_code == 200
    assert listing.json()["resources"] == [resource]

    update = client.patch(f"/api/network-resources/{resource['id']}", json={"manualMd": "Nur IoT"})

    assert update.status_code == 200
    assert update.json()["resource"]["manualMd"] == "Nur IoT"


def test_network_resource_manual_update_returns_404_for_unknown_resource(client):
    response = client.patch("/api/network-resources/missing", json={"manualMd": "Notiz"})

    assert response.status_code == 404
