"""Light HTTP-level smoke tests for the account assignment routes: they exist to catch wiring
mistakes in main.py itself (route path, request/response shape)."""
import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main


@pytest.fixture()
def client(temp_db, tmp_path, monkeypatch):
    # crypto._fernet() lazily creates/reads a key file next to the (real, non-test) DB by default
    # -- redirected into the same throwaway tmp_path temp_db already isolates everything else into.
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_assignment_round_trip(client):
    account = db.create_account({"label": "Aruba Switch Admin", "category": "login", "allowProbe": 1})

    put_response = client.put(
        f"/api/accounts/{account['id']}/assignments",
        json=[{"targetType": "kind", "targetValue": "network"}],
    )
    assert put_response.status_code == 200
    assert put_response.json()["assignments"][0]["targetValue"] == "network"

    get_response = client.get(f"/api/accounts/{account['id']}/assignments")
    assert get_response.status_code == 200
    assert len(get_response.json()["assignments"]) == 1

    listing = client.get("/api/accounts").json()["accounts"]
    assert next(a for a in listing if a["id"] == account["id"])["assignmentCount"] == 1
    # Never a plaintext secret anywhere in the list response.
    assert all("secretEnc" not in a and "passphraseEnc" not in a for a in listing)


def test_assignments_404_for_unknown_account(client):
    assert client.get("/api/accounts/does-not-exist/assignments").status_code == 404
    assert client.put("/api/accounts/does-not-exist/assignments", json=[]).status_code == 404


