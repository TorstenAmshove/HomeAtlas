"""The device config history was removed (issue #230): the table is dropped on startup
(idempotent), the stale `configVersionKeep` setting no longer breaks the settings API, and the two
routes are gone."""
import json

from fastapi.testclient import TestClient

from app import main


def _tables(db) -> set[str]:
    with db._conn() as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_init_db_drops_old_table_and_index_idempotently(temp_db):
    with temp_db._conn() as conn:
        conn.execute("CREATE TABLE deviceConfigVersions (id TEXT PRIMARY KEY, systemId TEXT NOT NULL, "
                     "label TEXT, content TEXT, source TEXT, createdAt TEXT)")
        conn.execute("CREATE INDEX idx_configversions_system ON deviceConfigVersions(systemId, createdAt DESC)")
        conn.execute("INSERT INTO deviceConfigVersions VALUES ('v1', 's1', 'l', 'enc', 'ssh', 'now')")
    temp_db.init_db()
    temp_db.init_db()
    names = _tables(temp_db)
    assert "deviceConfigVersions" not in names and "idx_configversions_system" not in names


def test_fresh_db_has_no_config_table(temp_db):
    temp_db.init_db()
    assert "deviceConfigVersions" not in _tables(temp_db)


def test_stale_setting_is_removed_and_settings_api_still_works(temp_db):
    with temp_db._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('app', ?)",
                     (json.dumps({"configVersionKeep": 50, "scanAutoEnabled": False}),))
    temp_db.init_db()
    assert "configVersionKeep" not in temp_db.get_settings()
    user = {"id": "u1", "role": "ADMIN", "username": "admin", "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    try:
        client = TestClient(main.app)
        current = client.get("/api/settings").json()
        settings = current.get("settings", current)
        assert "configVersionKeep" not in settings
        assert client.patch("/api/settings", json=settings).status_code == 200
    finally:
        main.app.dependency_overrides.clear()


def test_config_version_routes_are_gone(temp_db):
    system = temp_db.create_system({"name": "Core Switch", "kind": "network"})
    user = {"id": "u1", "role": "ADMIN", "username": "admin", "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    try:
        client = TestClient(main.app)
        assert client.get(f"/api/systems/{system['id']}/config-versions").status_code in (404, 405)
        assert client.get(f"/api/systems/{system['id']}/config-versions/x").status_code in (404, 405)
    finally:
        main.app.dependency_overrides.clear()
