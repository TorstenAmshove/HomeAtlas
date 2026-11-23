"""Access-log entries for account and network-note changes (#122): names only, never secrets."""
from pathlib import Path

from app import auth, db
from tests.test_auth_login import _code, _login, _user
from tests.test_users_api import _admin, env  # noqa: F401  (env is a fixture)

SECRET, PHRASE = "geheim123", "phrase456"


def _log(*actions):
    return [e for e in db.list_access_log() if e["action"] in actions]


def _create(client, **extra):
    r = client.post("/api/accounts", json={"label": "Router", "secret": SECRET,
                                           "passphrase": PHRASE, **extra})
    assert r.status_code == 200
    return r.json()["account"]["id"]


def test_create_is_logged_without_secrets(env):  # noqa: F811
    client = _admin(env)
    _create(client)
    (entry,) = _log("account.create")
    assert entry["detail"] == "Router" and entry["username"] == "root"
    assert SECRET not in str(entry) and PHRASE not in str(entry)


def test_update_variants(env):  # noqa: F811
    client = _admin(env)
    aid = _create(client)
    assert client.patch(f"/api/accounts/{aid}", json={"allowProbe": True}).status_code == 200
    assert client.patch(f"/api/accounts/{aid}", json={"secret": "neu-geheim"}).status_code == 200
    assert client.patch(f"/api/accounts/{aid}", json={"clearSecrets": ["passphrase"]}).status_code == 200
    assert client.patch(f"/api/accounts/{aid}", json={}).status_code == 200
    details = [e["detail"] for e in reversed(_log("account.update"))]
    assert details == ["Router: Scan-Freigabe", "Router: Passwort", "Router: Passphrase entfernt"]
    assert "neu-geheim" not in str(db.list_access_log())


def test_rejected_changes_are_not_logged(env):  # noqa: F811
    client = _admin(env)
    aid = _create(client)
    before = len(_log("account.update", "account.create", "account.delete"))
    r = client.patch(f"/api/accounts/{aid}", json={"secret": "wert-xyz", "clearSecrets": ["secret"]})
    assert r.status_code == 422
    assert client.patch(f"/api/accounts/{aid}", json={"systemId": "nope"}).status_code == 422
    assert client.patch("/api/accounts/nope", json={"url": "x"}).status_code == 404
    assert client.post("/api/accounts", json={"systemId": "nope"}).status_code == 422
    assert client.delete("/api/accounts/nope").status_code == 404
    assert len(_log("account.update", "account.create", "account.delete")) == before
    assert "wert-xyz" not in str(db.list_access_log())


def test_delete_is_logged_and_long_label_truncated(env):  # noqa: F811
    client = _admin(env)
    aid = _create(client, label="L" * 600)
    assert client.delete(f"/api/accounts/{aid}").status_code == 200
    (entry,) = _log("account.delete")
    assert entry["detail"] == "L" * 500


def test_member_cannot_change_and_nothing_is_logged(env):  # noqa: F811
    _user("mem", role=auth.ROLE_MEMBER)
    from fastapi.testclient import TestClient

    from app import main
    _, secret = _user("mem2", role=auth.ROLE_MEMBER)
    client = TestClient(main.app)
    assert _login(client, "mem2", code=_code(secret)).status_code == 200
    assert client.post("/api/accounts", json={"label": "x"}).status_code == 403
    assert _log("account.create") == []


def test_all_new_actions_have_frontend_labels():
    ts = (Path(__file__).resolve().parents[2] / "frontend/src/pages/mehr/accessLogLabels.ts").read_text()
    for action in ("user.delete", "account.create", "account.update", "account.delete",
                   "networkresource.update"):
        assert f'"{action}"' in ts
    assert "mfa.disable" not in ts
