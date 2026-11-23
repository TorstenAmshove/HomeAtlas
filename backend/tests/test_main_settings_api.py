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
        body = client.get("/api/settings").json()["settings"]
        assert "uiCalm" not in body
        assert client.patch("/api/settings", json={"homeName": "X"}).status_code == 200
        assert db.get_settings()["uiCalm"] is True
        assert client.patch("/api/settings", json={"uiCalm": "yes"}).status_code == 422
    finally:
        main.app.dependency_overrides.clear()


def test_defaults_cover_provider_keys():
    from app import llm_providers
    keys = set(llm_providers._MODEL_SETTING_FIELD.values()) | set(llm_providers._KEY_SETTING_FIELD.values())
    keys |= {field for field, _ in llm_providers._BASE_URL_SETTING_FIELD.values()}
    assert keys <= set(db.DEFAULT_SETTINGS)


def test_settings_patch_covers_defaults():
    from app.routes import settings as routes_settings
    fields = set(routes_settings.SettingsPatch.model_fields)
    internal = {k for k in db.DEFAULT_SETTINGS if k.endswith("Enc")}
    assert set(db.DEFAULT_SETTINGS) - internal <= fields


def _patch(body):
    client, main = _admin_client()
    try:
        return client.patch("/api/settings", json=body)
    finally:
        main.app.dependency_overrides.clear()


def test_patch_unknown_key_422(temp_db):
    assert _patch({"doesNotExist": 1}).status_code == 422


def test_patch_wrong_type_422(temp_db):
    for body in ({"scanTimeoutMs": True}, {"scanTimeoutMs": "1"}, {"homeName": None},
                 {"homeName": ["a"]}, {"scanEnableMdns": "yes"}, {"llmProvider": "NOPE"},
                 {"scanSubnets": "10.0.0.0/24"}):
        assert _patch(body).status_code == 422, body


def test_patch_setup_completed_unchanged(temp_db):
    assert _patch({"setupCompleted": True}).status_code == 200
    assert db.get_settings()["setupCompleted"] is False


def test_patch_raw_enc_rejected(temp_db):
    assert _patch({"defaultCredentialSecretEnc": "x"}).status_code == 422


def test_get_roundtrip_patch_ok(temp_db):
    db.update_settings({"claudeApiKey": "enc-placeholder", "defaultCredentialSecretEnc": "e"})
    client, main = _admin_client()
    try:
        before = db.get_settings()
        body = client.get("/api/settings").json()["settings"]
        assert client.patch("/api/settings", json=body).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
    assert db.get_settings() == before


def test_member_get_unchanged(temp_db):
    from fastapi.testclient import TestClient

    from app import auth, main
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        settings = TestClient(main.app).get("/api/settings").json()["settings"]
    finally:
        main.app.dependency_overrides.clear()
    assert set(settings) == {"homeName", "setupCompleted"}


def test_patch_invalid_scan_subnet_422(temp_db):
    before = db.get_settings()
    for entries, bad in ((["bad"], "bad"), (["10.0.0.0/24", "x"], "x"), (["2001:db8::/64"], "2001:db8::/64")):
        response = _patch({"scanSubnets": entries})
        assert response.status_code == 422, entries
        assert bad in response.text
    assert db.get_settings() == before


def test_patch_scan_subnets_trimmed_normalised(temp_db):
    response = _patch({"scanSubnets": [" 10.0.0.5/24 ", "", "10.0.0.0/24"]})
    assert response.status_code == 200
    assert db.get_settings()["scanSubnets"] == ["10.0.0.0/24"]


def test_patch_without_scan_subnets_ignores_validator(temp_db):
    assert _patch({"homeName": "Y"}).status_code == 200
    assert _patch({"scanSubnets": []}).status_code == 200
