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


def _with_account():
    s = db.create_system({"name": "A", "ip": "10.0.0.1"})
    db.create_account({"systemId": s["id"], "label": "x", "category": "login"})
    return s


def test_delete_requires_admin(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        assert TestClient(main.app).delete("/api/systems/x").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_delete_unknown_id_is_404(client):
    assert client.delete("/api/systems/nope").status_code == 404


def test_delete_with_accounts_needs_parameter(client):
    s = _with_account()
    for suffix in ("", "?withAccounts=false"):
        r = client.delete(f"/api/systems/{s['id']}{suffix}")
        assert r.status_code == 409
        assert isinstance(r.json()["detail"], str) and "1" in r.json()["detail"]
    assert db.get_system(s["id"]) is not None
    assert len(db.list_accounts(s["id"])) == 1


def test_delete_with_accounts_parameter_removes_both(client):
    s = _with_account()
    assert client.delete(f"/api/systems/{s['id']}?withAccounts=true").json() == {"ok": True}
    assert db.get_system(s["id"]) is None
    assert db.list_accounts(s["id"]) == []


def test_delete_without_accounts_needs_no_parameter(client):
    s = db.create_system({"name": "B", "ip": "10.0.0.2"})
    assert client.delete(f"/api/systems/{s['id']}").status_code == 200
    assert db.get_system(s["id"]) is None
