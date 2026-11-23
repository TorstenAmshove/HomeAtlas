"""User API consistency (#123): 404 on delete, atomic PATCH, role and name validation."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, security
from tests.test_auth_login import _code, _login, _user

STRONG = "Anderes-Pferd-Batterie-7"


@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    monkeypatch.setattr(security, "login_throttle", security.LoginThrottle())
    main.app.dependency_overrides.clear()
    return temp_db


def _admin(env, name="root"):
    _, secret = _user(name)
    client = TestClient(main.app)
    assert _login(client, name, code=_code(secret)).status_code == 200
    return client


def test_delete_unknown_user_is_404(env):
    client = _admin(env)
    assert client.delete("/api/users/gibts-nicht").status_code == 404


def test_delete_self_and_last_admin_still_400(env):
    client = _admin(env)
    me = client.get("/api/auth/me").json()["user"]["id"]
    assert client.delete(f"/api/users/{me}").status_code == 400
    other, _ = _user("zwei", role=auth.ROLE_ADMIN, totp=False)
    db.update_user(me, {"role": auth.ROLE_MEMBER})  # force: only "zwei" is admin now
    assert client.delete(f"/api/users/{other}").status_code in (400, 403)


def test_patch_weak_password_changes_nothing(env):
    client = _admin(env)
    uid, _ = _user("bob", role=auth.ROLE_ADMIN, totp=False)
    _user("carl", role=auth.ROLE_ADMIN, totp=False)
    token = auth.create_session(uid)
    before = len(db.list_access_log())
    r = client.patch(f"/api/users/{uid}", json={"displayName": "Neu", "role": auth.ROLE_MEMBER, "newPassword": "x"})
    assert r.status_code == 400
    after = db.get_user(uid)
    assert after["displayName"] != "Neu" and after["role"] == auth.ROLE_ADMIN
    assert db.get_db_session(token) is not None
    assert len(db.list_access_log()) == before


def test_patch_invalid_role_and_weak_password_reports_role_first(env):
    client = _admin(env)
    uid, _ = _user("bob", role=auth.ROLE_MEMBER, totp=False)
    r = client.patch(f"/api/users/{uid}", json={"role": "ROOT", "newPassword": "x"})
    assert r.status_code == 400 and "Rolle" in r.json()["detail"]


def test_patch_unknown_role_is_400(env):
    client = _admin(env)
    uid, _ = _user("bob", role=auth.ROLE_MEMBER, totp=False)
    assert client.patch(f"/api/users/{uid}", json={"role": "ROOT"}).status_code == 400


def test_patch_last_admin_cannot_demote(env):
    client = _admin(env)
    me = client.get("/api/auth/me").json()["user"]["id"]
    assert client.patch(f"/api/users/{me}", json={"role": auth.ROLE_MEMBER}).status_code == 400


def test_create_user_unknown_role_is_400(env):
    client = _admin(env)
    r = client.post("/api/users", json={"username": "neu", "password": STRONG, "role": "ROOT"})
    assert r.status_code == 400 and r.json()["detail"] == "Unbekannte Rolle."
    assert db.get_user_by_username_raw("neu") is None


def test_create_user_trims_and_validates_name(env):
    client = _admin(env)
    ok = client.post("/api/users", json={"username": "  Anna  ", "password": STRONG})
    assert ok.status_code == 200 and ok.json()["user"]["username"] == "Anna"
    assert client.post("/api/users", json={"username": "a b", "password": STRONG}).status_code == 400
    assert client.post("/api/users", json={"username": "   ", "password": STRONG}).status_code == 400


def test_create_duplicate_other_case_is_409(env):
    client = _admin(env)
    _user("anna", totp=False)
    r = client.post("/api/users", json={"username": "Anna", "password": STRONG})
    assert r.status_code == 409


def test_exact_duplicate_race_maps_to_409(env, monkeypatch):
    client = _admin(env)
    monkeypatch.setattr(db, "username_taken", lambda _n: False)
    _user("anna", totp=False)

    def boom(*a, **k):
        raise sqlite3.IntegrityError("UNIQUE")
    monkeypatch.setattr(db, "create_user", boom)
    assert client.post("/api/users", json={"username": "anna", "password": STRONG}).status_code == 409


def test_login_is_case_insensitive_and_trims(env):
    _user("Anna", totp=False)
    assert _login(TestClient(main.app), "  anna ").status_code == 200


def test_legacy_case_duplicates_exact_login_works_ambiguous_fails(env):
    _user("anna", totp=False)
    _user("ANNA", totp=False)
    assert _login(TestClient(main.app), "anna").status_code == 200
    assert _login(TestClient(main.app), "ANNA").status_code == 200
    assert _login(TestClient(main.app), "Anna").status_code == 401


def test_throttle_counts_case_variants():
    t = security.LoginThrottle()
    assert t._keys("Anna", "1.1.1.1") == t._keys(" anna ", "1.1.1.1")


def test_self_demotion_locks_admin_routes(env):
    client = _admin(env)
    me = client.get("/api/auth/me").json()["user"]["id"]
    _user("zwei", role=auth.ROLE_ADMIN, totp=False)
    assert client.patch(f"/api/users/{me}", json={"role": auth.ROLE_MEMBER}).status_code == 200
    assert client.get("/api/auth/me").json()["user"]["role"] == auth.ROLE_MEMBER
    assert client.get("/api/users").status_code == 403


def test_delete_user_is_logged(env):
    client = _admin(env)
    uid, _ = _user("bob", role=auth.ROLE_MEMBER, totp=False)
    assert client.delete(f"/api/users/{uid}").status_code == 200
    entries = db.list_access_log(action="user.delete")
    assert len(entries) == 1
    assert entries[0]["detail"] == "bob" and entries[0]["username"] == "root" and entries[0]["ok"] == 1


def test_rejected_user_delete_is_not_logged(env):
    client = _admin(env)
    me = client.get("/api/auth/me").json()["user"]["id"]
    assert client.delete("/api/users/gibts-nicht").status_code == 404
    assert client.delete(f"/api/users/{me}").status_code == 400
    assert db.list_access_log(action="user.delete") == []
