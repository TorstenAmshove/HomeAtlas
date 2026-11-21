"""Controller-network selection is stored through the generic settings merge."""
from app import db


def test_controller_network_selection_roundtrip(temp_db):
    temp_db.update_settings({"scanControllerNetworkIds": ["a"], "scanControllerNetworksSeen": ["a", "b"]})
    temp_db.update_settings({"homeName": "X"})
    settings = db.get_settings()
    assert settings["scanControllerNetworkIds"] == ["a"]
    assert settings["scanControllerNetworksSeen"] == ["a", "b"]
    assert db.DEFAULT_SETTINGS["scanControllerNetworkIds"] == []


def _admin_client():
    from fastapi.testclient import TestClient

    from app import auth, main
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    return TestClient(main.app), main


def test_health_has_no_ui_calm(temp_db):
    client, main = _admin_client()
    try:
        body = client.get("/api/health").json()
    finally:
        main.app.dependency_overrides.clear()
    assert set(body) == {"status", "setupCompleted", "userCount"}


def test_legacy_ui_calm_key_is_harmless(temp_db):
    # Existing installations still carry "uiCalm": true in the stored settings JSON.
    db.update_settings({"uiCalm": True})
    client, main = _admin_client()
    try:
        assert client.get("/api/settings").status_code == 200
        assert client.patch("/api/settings", json={"homeName": "X"}).status_code == 200
        assert db.get_settings()["uiCalm"] is True
        # An unknown key is no longer validated.
        assert client.patch("/api/settings", json={"uiCalm": "yes"}).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
