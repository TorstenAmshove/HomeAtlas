# ruff: noqa: F811
"""#128: input validation of the accounts API (category, systemId, clearing secrets, deploy
login category, 404 on delete)."""
import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main
from tests.test_llm_defaults_and_accounts import admin, keyed  # noqa: F401


def _account(**kw):
    return db.create_account({"label": "A", "category": "login", **kw})


@pytest.mark.parametrize("category,status", [("bogus", 422), ("router", 422), ("omada", 422), ("adguard", 422), ("snmp", 200)])
def test_category_validated(admin, category, status):
    assert admin.post("/api/accounts", json={"category": category}).status_code == status
    account = _account()
    assert admin.patch(f"/api/accounts/{account['id']}", json={"category": category}).status_code == status


def test_clear_secrets_empties_only_named_field(admin):
    account = _account(secretEnc=crypto.encrypt("pw"), passphraseEnc=crypto.encrypt("pp"))
    assert admin.patch(f"/api/accounts/{account['id']}", json={"clearSecrets": ["secret"]}).status_code == 200
    stored = db.get_account(account["id"])
    assert crypto.decrypt(stored["secretEnc"]) == "" and crypto.decrypt(stored["passphraseEnc"]) == "pp"
    assert admin.patch(f"/api/accounts/{account['id']}", json={"clearSecrets": ["passphrase"]}).status_code == 200
    assert crypto.decrypt(db.get_account(account["id"])["passphraseEnc"]) == ""


def test_clear_secrets_conflict_422_without_echo(admin):
    account = _account(secretEnc=crypto.encrypt("pw"))
    for name in ("secret", "passphrase"):
        response = admin.patch(f"/api/accounts/{account['id']}",
                               json={"clearSecrets": [name], name: "geheim-xyz"})
        assert response.status_code == 422 and "geheim-xyz" not in response.text
    assert crypto.decrypt(db.get_account(account["id"])["secretEnc"]) == "pw"


def test_clear_secrets_unknown_name_422(admin):
    account = _account()
    assert admin.patch(f"/api/accounts/{account['id']}", json={"clearSecrets": ["label"]}).status_code == 422


def test_empty_secret_without_clear_keeps_stored(admin):
    account = _account(secretEnc=crypto.encrypt("pw"))
    admin.patch(f"/api/accounts/{account['id']}", json={"secret": "", "clearSecrets": []})
    assert crypto.decrypt(db.get_account(account["id"])["secretEnc"]) == "pw"


def test_unknown_system_422(admin):
    assert admin.post("/api/accounts", json={"systemId": "nope"}).status_code == 422
    account = _account()
    assert admin.patch(f"/api/accounts/{account['id']}", json={"systemId": "nope"}).status_code == 422
    assert admin.patch("/api/accounts/missing", json={"systemId": "nope"}).status_code == 404


def test_system_null_and_empty_allowed(admin):
    system = db.create_system({"name": "NAS", "kind": "nas", "ip": "192.168.1.20"})
    account = _account(systemId=system["id"])
    assert admin.patch(f"/api/accounts/{account['id']}", json={"systemId": None}).status_code == 200
    assert admin.patch(f"/api/accounts/{account['id']}", json={"systemId": ""}).status_code == 200
    assert admin.post("/api/accounts", json={"systemId": None}).status_code == 200
    assert admin.post("/api/accounts", json={"systemId": system["id"]}).status_code == 200
    db.delete_system(system["id"])
    assert admin.patch(f"/api/accounts/{account['id']}", json={"systemId": system["id"]}).status_code == 422


def test_delete_unknown_404_then_ok(admin):
    assert admin.delete("/api/accounts/missing").status_code == 404
    account = _account()
    assert admin.delete(f"/api/accounts/{account['id']}").status_code == 200
    assert admin.delete(f"/api/accounts/{account['id']}").status_code == 404


def test_delete_member_403(keyed):  # noqa: F811
    main.app.dependency_overrides[main.current_user] = lambda: {
        "id": "m", "role": auth.ROLE_MEMBER, "username": "m", "totpEnabled": 1}
    try:
        assert TestClient(main.app).delete("/api/accounts/x").status_code == 403
    finally:
        main.app.dependency_overrides.clear()

