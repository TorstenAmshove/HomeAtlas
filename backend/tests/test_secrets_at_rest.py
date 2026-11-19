"""Secrets that older versions stored readably (#41, #42): config exports in systems.extra.probe
(and from there in docs, page versions and assistant tool results), and LLM API keys in the
settings blob. Covers the write paths that no longer store them, the read paths that no longer
expose them, and the one-time startup migration (main._migrate_plaintext_secrets)."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, docs, llm_providers, main, probe_auth

EXPORT = "snmp-server community S3cr3tCommunity\nradius-server key R4diusKey"


@pytest.fixture()
def keyed(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    return temp_db


def _client(role: str) -> TestClient:
    user = {"id": "u1", "role": role, "username": role.lower(), "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    return TestClient(main.app)


@pytest.fixture()
def member(keyed):
    try:
        yield _client(auth.ROLE_MEMBER)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def admin(keyed):
    try:
        yield _client(auth.ROLE_ADMIN)
    finally:
        main.app.dependency_overrides.clear()


def _probe_results() -> dict:
    return {"ssh:Switch": {"ok": True, "facts": {
        "hostname": {"label": "Hostname", "value": "core-sw"},
        "config_export": {"label": "Vollständige Konfiguration", "value": EXPORT},
    }}}


# --- write path -------------------------------------------------------------------------------

def test_without_config_backups_strips_only_export_facts():
    cleaned = probe_auth.without_config_backups(_probe_results())
    assert set(cleaned["ssh:Switch"]["facts"]) == {"hostname"}


def test_config_backup_labels_cover_every_export_command():
    """CONFIG_BACKUP_LABELS drives the doc/chat scrub; a new export command with another label
    would silently slip through it."""
    source = Path(probe_auth.__file__).read_text(encoding="utf-8")
    labels = set(re.findall(r'\("(?:config_export|omada_backup)",\s*"([^"]+)"', source))
    assert labels and labels <= set(probe_auth.CONFIG_BACKUP_LABELS)


# --- read paths -------------------------------------------------------------------------------

def test_docs_never_render_config_export_even_from_old_rows(keyed):
    system = db.create_system({"name": "Core Switch", "kind": "network", "ip": "10.0.0.2"})
    db.update_system(system["id"], {"extra": {"probe": _probe_results()}})
    rendered = docs._device_details([db.get_system(system["id"])], {}, {})
    assert "core-sw" in rendered
    assert "S3cr3tCommunity" not in rendered


def test_config_versions_are_admin_only(member):
    system = db.create_system({"name": "Core Switch", "kind": "network"})
    version = db.save_device_config_version(system["id"], "Core Switch – Vollständige Konfiguration",
                                            crypto.encrypt(EXPORT), "ssh:Switch")
    assert member.get(f"/api/systems/{system['id']}/config-versions").status_code == 403
    assert member.get(f"/api/systems/{system['id']}/config-versions/{version['id']}").status_code == 403


def test_admin_still_reads_config_version(admin):
    system = db.create_system({"name": "Core Switch", "kind": "network"})
    version = db.save_device_config_version(system["id"], "Core Switch – Vollständige Konfiguration",
                                            crypto.encrypt(EXPORT), "ssh:Switch")
    response = admin.get(f"/api/systems/{system['id']}/config-versions/{version['id']}")
    assert response.status_code == 200
    assert response.json()["version"]["content"] == EXPORT


# --- API keys ---------------------------------------------------------------------------------

def test_api_key_is_stored_encrypted_and_masked(admin):
    response = admin.patch("/api/settings", json={"llmProvider": "CLAUDE", "claudeApiKey": "sk-test-123"})
    assert response.status_code == 200
    assert response.json()["settings"]["claudeApiKey"] == "********"
    stored = db.get_settings()["claudeApiKey"]
    assert stored != "sk-test-123" and crypto.is_encrypted(stored)
    assert llm_providers.api_key_for("CLAUDE", db.get_settings()) == "sk-test-123"


def test_masked_round_trip_keeps_key_and_blank_clears_it(admin):
    admin.patch("/api/settings", json={"claudeApiKey": "sk-test-123"})
    admin.patch("/api/settings", json={"claudeApiKey": "********", "homeName": "X"})
    assert llm_providers.api_key_for("CLAUDE", db.get_settings()) == "sk-test-123"
    admin.patch("/api/settings", json={"claudeApiKey": ""})
    assert llm_providers.api_key_for("CLAUDE", db.get_settings()) == ""


def test_provider_test_uses_unsaved_plaintext_key(admin, monkeypatch):
    seen = {}

    async def fake_test(provider, settings):
        seen["key"] = llm_providers.api_key_for(provider, settings)
        return True, "ok", "m"

    monkeypatch.setattr(llm_providers, "test_connection", fake_test)
    admin.post("/api/settings/llm/test", json={"provider": "OPENAI", "settings": {"openAiApiKey": "sk-new"}})
    assert seen["key"] == "sk-new"
    assert db.get_settings()["openAiApiKey"] == ""  # testing never stores


# --- startup migration ------------------------------------------------------------------------

def test_migration_encrypts_keys_and_scrubs_exports(keyed):
    db.update_settings({"deepseekApiKey": "sk-plain"})
    system = db.create_system({"name": "Core Switch", "kind": "network"})
    db.update_system(system["id"], {"extra": {"probe": _probe_results(), "docker": {"x": 1}}})
    body = ("# Netzwerk\n\n- **Hostname:** core-sw\n- **Vollständige Konfiguration:**\n\n  ```\n  "
            + EXPORT.replace("\n", "\n  ") + "\n  ```\n\n- **Zuletzt gesehen:** heute\n"
            "- **Omada-Controller-Sicherung (neueste Datei, Base64):** QUJD\n")
    db.upsert_doc_page("netzwerk", "netzwerk", "Netzwerk", body, "", 1)
    db.snapshot_doc_page("netzwerk", "test")
    chat = db.create_chat()
    db.add_chat_message(chat["id"], "tool", json.dumps({"page": body}, ensure_ascii=False), tool_call_id="t1")
    db.add_chat_message(chat["id"], "tool", json.dumps({"ok": True}), tool_call_id="t2")

    main._migrate_plaintext_secrets()

    stored = db.get_settings()["deepseekApiKey"]
    assert crypto.is_encrypted(stored) and crypto.decrypt(stored) == "sk-plain"
    extra = db.get_system(system["id"])["extra"]
    assert set(extra["probe"]["ssh:Switch"]["facts"]) == {"hostname"}
    assert extra["docker"] == {"x": 1}
    page = db.get_doc_page("netzwerk")["bodyMd"]
    assert "S3cr3t" not in page and "QUJD" not in page
    assert "- **Hostname:** core-sw" in page and "- **Zuletzt gesehen:** heute" in page
    with db._conn() as conn:
        versions = [r["bodyMd"] for r in conn.execute("SELECT bodyMd FROM docPageVersions")]
    assert versions and all("S3cr3t" not in v for v in versions)
    tool_contents = [m["content"] for m in db.list_chat_messages(chat["id"])]
    assert all("S3cr3t" not in c for c in tool_contents)
    assert json.loads(tool_contents[1]) == {"ok": True}

    # Idempotent: a second run changes nothing and does not double-encrypt.
    main._migrate_plaintext_secrets()
    assert db.get_settings()["deepseekApiKey"] == stored
