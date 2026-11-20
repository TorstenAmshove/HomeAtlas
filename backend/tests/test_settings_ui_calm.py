"""Feature flag for the redesigned UI shell (`uiCalm`, docs/redesign/5-information-architecture.md):
default off, env fallback only while never set, exposed in /api/health, admin-writable."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


@pytest.fixture()
def client(temp_db, monkeypatch):
    monkeypatch.delenv(db.UI_CALM_DEFAULT_ENV, raising=False)
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_default_off_and_in_health(client):
    assert db.ui_calm() is False
    body = client.get("/api/health").json()
    assert body["uiCalm"] is False
    assert "setupCompleted" in body


def test_env_default_applies_only_while_never_set(client, monkeypatch):
    monkeypatch.setenv(db.UI_CALM_DEFAULT_ENV, "1")
    assert client.get("/api/health").json()["uiCalm"] is True
    # Unrelated saves (setup wizard, other settings tabs) do not freeze the fallback ...
    db.update_settings({"homeName": "X"})
    assert db.UI_CALM_KEY not in db.get_settings()
    # ... and neither does a whole-form save that echoes the effective value back.
    client.patch("/api/settings", json={"homeName": "Y", "uiCalm": True})
    assert db.UI_CALM_KEY not in db.get_settings()
    # An explicit change is stored and then wins over the env var.
    response = client.patch("/api/settings", json={"uiCalm": False})
    assert response.status_code == 200
    assert response.json()["settings"]["uiCalm"] is False
    assert client.get("/api/health").json()["uiCalm"] is False


def test_admin_toggle_roundtrip(client):
    response = client.patch("/api/settings", json={"uiCalm": True})
    assert response.json()["settings"]["uiCalm"] is True
    assert db.get_settings()["uiCalm"] is True
    assert client.get("/api/health").json()["uiCalm"] is True
    client.patch("/api/settings", json={"uiCalm": False})
    assert client.get("/api/health").json()["uiCalm"] is False


def test_member_cannot_write(temp_db, monkeypatch):
    monkeypatch.delenv(db.UI_CALM_DEFAULT_ENV, raising=False)
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        assert TestClient(main.app).patch("/api/settings", json={"uiCalm": True}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()
    assert db.ui_calm() is False
