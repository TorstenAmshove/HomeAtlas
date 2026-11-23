"""GET /api/scans* is admin-only: the log holds device names and probe error texts (issue #119)."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


def _as(role):
    main.app.dependency_overrides[main.current_user] = lambda: {
        "id": "u", "role": role, "username": "u", "totpEnabled": 1}
    return TestClient(main.app)


@pytest.fixture()
def scan_id(temp_db):
    sid = db.create_scan("192.168.1.0/24")
    db.update_scan(sid, log_line="Gerät fritz.box gefunden")
    yield sid
    main.app.dependency_overrides.clear()


def test_member_forbidden(scan_id):
    c = _as(auth.ROLE_MEMBER)
    assert c.get("/api/scans").status_code == 403
    assert c.get(f"/api/scans/{scan_id}").status_code == 403


def test_admin_allowed(scan_id):
    c = _as(auth.ROLE_ADMIN)
    r = c.get("/api/scans")
    assert r.status_code == 200 and "log" not in r.json()["scans"][0]
    assert "fritz.box" in c.get(f"/api/scans/{scan_id}").json()["scan"]["log"]
    assert c.get("/api/scans/unknown").status_code == 404
