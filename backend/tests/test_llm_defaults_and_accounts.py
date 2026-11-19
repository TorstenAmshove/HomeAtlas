"""#46: no LLM call without a configured provider, and provider network errors are non-fatal.
#47: PATCH on an account changes only what was sent; deploying a key uses the key itself, not
the editable notes field."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, classify, crypto, db, docs, llm_providers, main, remote_admin


@pytest.fixture()
def keyed(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    return temp_db


def _finding() -> dict:
    return {"ip": "192.168.1.50", "kind": "other", "vendor": "Acme", "openPorts": [80], "extra": {}}


# --- #46 --------------------------------------------------------------------------------------

def test_is_configured(keyed):
    assert llm_providers.is_configured("OLLAMA", {}) is True
    assert llm_providers.is_configured("DEEPSEEK", {"deepseekApiKey": ""}) is False
    assert llm_providers.is_configured("", {}) is False
    assert llm_providers.is_configured("DEEPSEEK", {"deepseekApiKey": crypto.encrypt("sk-1")}) is True


def test_classify_without_key_sends_nothing(keyed, monkeypatch):
    async def must_not_be_called(*args, **kwargs):
        raise AssertionError("LLM called without a configured provider")

    monkeypatch.setattr(llm_providers, "chat", must_not_be_called)
    by_ip, warnings = asyncio.run(classify.classify([_finding()], {"llmProvider": "DEEPSEEK", "deepseekApiKey": ""}))
    assert by_ip == {}
    assert any("übersprungen" in w for w in warnings)


def test_doc_intro_without_key_uses_fallback(keyed, monkeypatch):
    async def must_not_be_called(*args, **kwargs):
        raise AssertionError("LLM called without a configured provider")

    monkeypatch.setattr(llm_providers, "chat", must_not_be_called)
    topic = next(t for t in docs.TOPICS if t.kinds)
    text = asyncio.run(docs._write_intro(topic, [], {"scanUseLlm": True, "llmProvider": "DEEPSEEK"}))
    assert text == topic.fallback


def test_network_error_becomes_provider_error(keyed, monkeypatch):
    async def unreachable(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm_providers, "_chat_openai_compatible", unreachable)
    monkeypatch.setattr(llm_providers, "resolved_model_for", lambda *a, **k: "some-model")
    with pytest.raises(llm_providers.ProviderError):
        asyncio.run(llm_providers.chat("OLLAMA", {}, "sys", [{"role": "user", "content": "hi"}]))


def test_classify_survives_network_error(keyed, monkeypatch):
    async def unreachable(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(llm_providers, "_chat_openai_compatible", unreachable)
    monkeypatch.setattr(llm_providers, "resolved_model_for", lambda *a, **k: "some-model")
    by_ip, warnings = asyncio.run(classify.classify([_finding()], {"llmProvider": "OLLAMA"}))
    assert by_ip == {} and warnings


# --- #47 --------------------------------------------------------------------------------------

@pytest.fixture()
def admin(keyed):
    main.app.dependency_overrides[main.current_user] = lambda: {
        "id": "a", "role": auth.ROLE_ADMIN, "username": "admin", "totpEnabled": 1}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_partial_patch_keeps_other_fields(admin):
    account = db.create_account({"label": "Switch", "category": "login", "username": "root",
                                 "notes": "Rack 2", "allowProbe": 1, "port": 2222})
    response = admin.patch(f"/api/accounts/{account['id']}", json={"label": "Core-Switch"})
    assert response.status_code == 200
    stored = db.get_account(account["id"])
    assert stored["label"] == "Core-Switch"
    assert stored["allowProbe"] == 1 and stored["notes"] == "Rack 2"
    assert stored["username"] == "root" and stored["port"] == 2222 and stored["category"] == "login"


def test_full_form_patch_still_works(admin):
    account = db.create_account({"label": "Switch", "category": "login", "allowProbe": 1})
    body = {"systemId": None, "label": "Switch", "category": "login", "username": "", "secret": "",
            "passphrase": "", "url": "", "notes": "", "allowProbe": False, "port": 0}
    assert admin.patch(f"/api/accounts/{account['id']}", json=body).status_code == 200
    assert db.get_account(account["id"])["allowProbe"] == 0


def test_public_line_is_derived_from_private_key():
    private_pem, public_line = remote_admin.generate_keypair(comment="homeatlas@NAS")
    derived = remote_admin.public_line_for(private_pem, "", comment="homeatlas@NAS  Keller\nx")
    assert derived.split()[:2] == public_line.split()[:2]
    assert "\n" not in derived and derived.endswith("homeatlas@NAS Keller x")
    with pytest.raises(ValueError):
        remote_admin.public_line_for("not a key")


def test_deploy_ignores_edited_notes(admin, monkeypatch):
    system = db.create_system({"name": "NAS", "kind": "nas", "ip": "192.168.1.20"})
    private_pem, public_line = remote_admin.generate_keypair(comment="homeatlas@NAS")
    key = db.create_account({"systemId": system["id"], "label": "Key", "category": "sshkey",
                             "secretEnc": crypto.encrypt(private_pem), "passphraseEnc": crypto.encrypt(""),
                             "notes": 'command="rm -rf /" ssh-ed25519 AAAAevil attacker'})
    login = db.create_account({"systemId": system["id"], "label": "Login", "category": "login",
                               "username": "root", "secretEnc": crypto.encrypt("pw")})
    seen = {}

    async def fake_deploy(host, account, line, port=0):
        seen["line"] = line
        return {"ok": True, "changed": True, "error": ""}

    monkeypatch.setattr(remote_admin, "deploy_public_key", fake_deploy)
    response = admin.post(f"/api/accounts/{key['id']}/deploy", json={"loginAccountId": login["id"]})
    assert response.status_code == 200
    assert seen["line"].split()[:2] == public_line.split()[:2]
    assert "command=" not in seen["line"] and "evil" not in seen["line"]
