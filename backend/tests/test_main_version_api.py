"""GET /api/version: login required, returns exactly the backend's release version."""
from fastapi.testclient import TestClient

from app import auth, main


def test_version_requires_login(temp_db):
    main.app.dependency_overrides.clear()
    assert TestClient(main.app).get("/api/version").status_code == 401


def test_version_returns_env_version(temp_db, monkeypatch):
    monkeypatch.setenv("HOMEATLAS_VERSION", "1.2.3")
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        resp = TestClient(main.app).get("/api/version")
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"version": "1.2.3"}
