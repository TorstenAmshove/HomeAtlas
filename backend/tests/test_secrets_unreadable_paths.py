"""#118: a secret the key can't open is an error everywhere it would be used, never an empty password."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, llm_providers, main, probe_auth, remote_admin

BAD = "gAAAAAB-kein-gueltiger-token"


@pytest.fixture(autouse=True)
def keyed(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)


@pytest.fixture()
def admin(keyed):
    user = {"id": "u1", "role": auth.ROLE_ADMIN, "username": "admin", "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_probe_ssh_unreadable_never_connects():
    r = asyncio.run(probe_auth.probe_ssh("192.0.2.1", {"secretEnc": BAD, "username": "root"}))
    assert r["ok"] is False and "nicht lesbar" in r["error"] and BAD not in r["error"]


def test_probe_decode_secret_unreadable_passphrase():
    acc = {"secretEnc": "", "passphraseEnc": BAD}
    with pytest.raises(crypto.SecretUnreadable):
        probe_auth._decode_secret(acc)


def test_probe_http_and_ha_unreadable():
    acc = {"secretEnc": BAD, "username": "u"}
    assert "nicht lesbar" in asyncio.run(probe_auth.probe_http("http://192.0.2.1", acc))["error"]
    assert "nicht lesbar" in asyncio.run(probe_auth.probe_homeassistant("http://192.0.2.1", acc))["error"]


def test_remote_admin_unreadable_returns_error():
    r = asyncio.run(remote_admin.deploy_public_key("192.0.2.1", {"secretEnc": BAD}, "ssh-ed25519 AAAA"))
    assert r["ok"] is False and "nicht lesbar" in r["error"]


def test_ha_switch_unreadable_returns_409_and_logs(admin):
    system = db.create_system({"name": "HA", "ip": "192.0.2.5"})
    acc = db.create_account({"label": "HA", "category": "homeassistant", "secretEnc": BAD,
                             "systemId": system["id"]})
    r = admin.post(f"/api/systems/{system['id']}/ha-switch/on",
                   params={"accountId": acc["id"], "entityId": "switch.x"})
    assert r.status_code == 409 and BAD not in r.text
    entries = [e for e in db.list_access_log() if e["action"] == "switch.ha"]
    assert len(entries) == 1 and entries[0]["ok"] == 0


def test_llm_unreadable_key():
    field = llm_providers._KEY_SETTING_FIELD["CLAUDE"]
    settings = {field: BAD}
    with pytest.raises(llm_providers.ProviderError):
        llm_providers.api_key_for("CLAUDE", settings)
    assert llm_providers.is_configured("CLAUDE", settings) is False
    ok, msg, models = asyncio.run(llm_providers.refresh_models("CLAUDE", settings))
    assert ok is False and "nicht lesbar" in msg
