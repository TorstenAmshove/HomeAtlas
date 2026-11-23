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


def _dev(name="A", **kw):
    return db.create_system({"name": name, **kw})


@pytest.mark.parametrize("body", [
    {"kind": "bogus"}, {"kind": None}, {"kind": ""}, {"kind": "Router"},
    {"importance": "bogus"}, {"importance": None}, {"importance": ""}, {"importance": "Critical"},
])
def test_patch_invalid_kind_importance_returns_422(client, body):
    a = _dev()
    assert client.patch(f"/api/systems/{a['id']}", json=body).status_code == 422


@pytest.mark.parametrize("ports", [[1, 2, 3, 4], [0], [65536], [-1], ["80"], [80.5], [True], [80, 80], "80"])
def test_patch_monitor_ports_invalid(client, ports):
    a = _dev()
    assert client.patch(f"/api/systems/{a['id']}", json={"monitorPorts": ports}).status_code == 422


def test_patch_monitor_ports_valid(client):
    a = _dev()
    for ports in ([], None, [80, 443, 65535]):
        r = client.patch(f"/api/systems/{a['id']}", json={"monitorPorts": ports})
        assert r.status_code == 200
        assert r.json()["system"]["monitorPorts"] == (ports or [])


def test_patch_parent_must_exist_not_self_no_cycle(client):
    a, b = _dev("A"), _dev("B")
    assert client.patch(f"/api/systems/{a['id']}", json={"parentId": "nope"}).status_code == 422
    assert client.patch(f"/api/systems/{a['id']}", json={"parentId": a["id"]}).status_code == 422
    assert client.patch(f"/api/systems/{a['id']}", json={"parentId": b["id"]}).status_code == 200
    assert client.patch(f"/api/systems/{b['id']}", json={"parentId": a["id"]}).status_code == 422
    for empty in (None, ""):
        client.patch(f"/api/systems/{a['id']}", json={"parentId": b["id"]})
        r = client.patch(f"/api/systems/{a['id']}", json={"parentId": empty})
        assert r.status_code == 200 and r.json()["system"]["parentId"] is None


def test_patch_unknown_id_still_404(client):
    assert client.patch("/api/systems/nope", json={"name": "x"}).status_code == 404


def test_patch_empty_body_sets_confirmed(client):
    a = _dev()
    r = client.patch(f"/api/systems/{a['id']}", json={})
    assert r.status_code == 200 and r.json()["system"]["confirmed"] == 1


def test_patch_critical_starts_monitoring(client):
    a = _dev(ip="10.0.0.9")
    r = client.patch(f"/api/systems/{a['id']}", json={"importance": "critical"})
    assert r.json()["system"]["monitored"] == 1


def test_patch_member_forbidden(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        c = TestClient(main.app)
        assert c.patch("/api/systems/x", json={"name": "y"}).status_code == 403
        assert c.post("/api/systems", json={"name": "y"}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_patch_ignores_system_fields(client):
    a = _dev("A", discoveryKey="k:a", status="online", openPorts=[22], extra={"x": 1})
    b = _dev("B", discoveryKey="k:b")
    r = client.patch(f"/api/systems/{b['id']}", json={
        "discoveryKey": "k:a", "status": "offline", "discovered": 1, "confirmed": 0, "extra": {"y": 2},
        "openPorts": [1], "lastSeen": "2000-01-01", "discoverySource": "x", "name": "B2"})
    assert r.status_code == 200
    got = r.json()["system"]
    assert got["name"] == "B2" and got["discoveryKey"] == "k:b" and got["status"] == b["status"]
    assert got["confirmed"] == 1 and got["extra"] == b["extra"] and got["openPorts"] == b["openPorts"]
    assert got["lastSeen"] == b["lastSeen"] and got["discovered"] == b["discovered"]
    assert db.get_system(a["id"])["discoveryKey"] == "k:a"


def test_patch_stale_body_keeps_scan_data(client):
    a = db.create_system({"name": "A", "discoveryKey": "k:a", "ip": "10.0.0.5", "status": "unknown"})
    stale = db.get_system(a["id"])
    db.update_system(a["id"], {"status": "online", "openPorts": [80], "extra": {"scan": 1},
                               "lastSeen": "2030-01-01T00:00:00+00:00"})
    r = client.patch(f"/api/systems/{a['id']}", json={**stale, "name": "Neu"})
    assert r.status_code == 200
    got = r.json()["system"]
    assert got["name"] == "Neu" and got["confirmed"] == 1
    assert got["status"] == "online" and got["openPorts"] == [80] and got["extra"] == {"scan": 1}
    assert got["lastSeen"].startswith("2030")


def test_post_ignores_client_id_and_system_fields(client):
    a = _dev("A", discoveryKey="k:a")
    r = client.post("/api/systems", json={"id": a["id"], "name": "N", "discoveryKey": "k:a",
                                          "status": "online", "extra": {"z": 1}})
    assert r.status_code == 200
    got = r.json()["system"]
    assert got["id"] != a["id"] and got["name"] == "N"
    assert got["discoveryKey"] != "k:a" and got["status"] == "unknown" and got["extra"] in (None, {}, "")
    assert got["confirmed"] == 1 and got["discovered"] == 0
    assert db.get_system(a["id"])["name"] == "A"


def test_post_invalid_kind_422(client):
    assert client.post("/api/systems", json={"name": "x", "kind": "bogus"}).status_code == 422


def test_post_unknown_parent_422(client):
    assert client.post("/api/systems", json={"name": "x", "parentId": "nope"}).status_code == 422


def test_post_minimal_name_kind(client):
    r = client.post("/api/systems", json={"name": "Drucker", "kind": "printer"})
    assert r.status_code == 200 and r.json()["system"]["kind"] == "printer"
