import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def _two(hostname="gw"):
    a = db.create_system({"name": "A", "hostname": hostname, "discoveryKey": "k:a"})
    b = db.create_system({"name": "B", "hostname": hostname, "discoveryKey": "k:b"})
    return a, b


def test_endpoints_require_admin(temp_db):
    member = {"role": auth.ROLE_MEMBER, "username": "m"}
    main.app.dependency_overrides[main.current_user] = lambda: member
    try:
        c = TestClient(main.app)
        assert c.get("/api/systems/duplicates").status_code == 403
        assert c.get("/api/systems/x/aliases").status_code == 403
        assert c.post("/api/systems/x/not-duplicate", json={"otherId": "y"}).status_code == 403
        assert c.post("/api/systems/x/merge", json={"removeId": "y"}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_duplicates_route_not_shadowed(client):
    a, b = _two()
    response = client.get("/api/systems/duplicates")
    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 1


def test_not_duplicate_endpoint(client):
    a, b = _two()
    assert client.post(f"/api/systems/{a['id']}/not-duplicate", json={}).status_code == 400
    assert client.post(f"/api/systems/{a['id']}/not-duplicate", json={"otherId": a["id"]}).status_code == 400
    assert client.post(f"/api/systems/{a['id']}/not-duplicate", json={"otherId": "nope"}).status_code == 404
    assert client.post(f"/api/systems/{a['id']}/not-duplicate", json={"otherId": b["id"]}).json() == {"ok": True}
    assert client.get("/api/systems/duplicates").json()["candidates"] == []


def test_aliases_endpoint(client):
    a, b = _two()
    db.merge_systems(a["id"], b["id"])
    aliases = client.get(f"/api/systems/{a['id']}/aliases").json()["aliases"]
    assert aliases[0]["aliasKey"] == "k:b" and "ip" in aliases[0] and "mac" in aliases[0]
    assert client.get("/api/systems/nope/aliases").status_code == 404
