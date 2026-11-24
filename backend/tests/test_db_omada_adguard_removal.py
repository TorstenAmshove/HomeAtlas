"""init_db drops the retired Omada/AdGuard Home accounts, scan switches and per-device stats (#227)."""
import json

from app import db


def _raw(sql, params=()):
    with db._conn() as conn:
        return conn.execute(sql, params).fetchall()


def _exec(sql, params=()):
    with db._conn() as conn:
        conn.execute(sql, params)


def _seed(category):
    system = db.create_system({"kind": "server", "name": f"S-{category}", "ip": "10.0.0.5"})
    acc = db.create_account({"systemId": system["id"], "label": category, "category": category})["id"]
    free = db.create_account({"label": f"{category}-free", "category": category})["id"]
    _exec("INSERT INTO accountAssignments (id, accountId, targetType, targetValue, createdAt) "
          "VALUES (?, ?, 'system', ?, 'x')", (f"as-{category}", acc, system["id"]))
    _exec("INSERT INTO networkResources (id, kind, source, sourceKey, sourceAccountId, siteExternalId, "
          "externalId, name, firstSeen, lastSeen, updatedAt) VALUES (?, 'network', ?, ?, ?, 's', 'e', 'n', "
          "'x', 'x', 'x')", (f"nr-{category}", category, f"k-{category}", acc))
    for table in ("exposureFacts", "firewallFacts"):
        _exec(f"INSERT INTO {table} (id, source, sourceAccountId, kind, key, firstSeen, lastSeen) "
              f"VALUES (?, ?, ?, 'k', 'k', 'x', 'x')", (f"{table}-{category}", category, acc))
    return system["id"], acc, free


def test_migration_removes_accounts_and_dependents(temp_db):
    keep = db.create_account({"label": "keep", "category": "unifi"})["id"]
    ids = [_seed("omada"), _seed("adguard")]

    db.init_db()
    db.init_db()  # idempotent

    assert db.get_account(keep) is not None
    for system_id, acc, free in ids:
        assert db.get_account(acc) is None and db.get_account(free) is None
        assert db.get_system(system_id) is not None
    assert not _raw("SELECT 1 FROM accountAssignments")
    assert not _raw("SELECT 1 FROM exposureFacts") and not _raw("SELECT 1 FROM firewallFacts")
    assert all(r["active"] == 0 for r in _raw("SELECT active FROM networkResources"))


def test_migration_cleans_settings_and_extra(temp_db):
    _exec("INSERT OR REPLACE INTO settings (key, value) VALUES ('app', ?)",
          (json.dumps({"scanEnableOmada": True, "scanEnableAdguard": False, "scanTimeoutMs": 900}),))
    a = db.create_system({"kind": "ap", "name": "A", "ip": "10.0.0.7"})["id"]
    b = db.create_system({"kind": "ap", "name": "B", "ip": "10.0.0.8"})["id"]
    c = db.create_system({"kind": "ap", "name": "C", "ip": "10.0.0.9"})["id"]
    _exec("UPDATE systems SET extra = ?, parentId = ?, updatedAt = 'U' WHERE id = ?",
          (json.dumps({"omada": {"x": 1}, "adguard": {"y": 2}, "unifi": {"z": 3}, "nameSource": "manual",
                       "parentSource": "manual"}), b, a))
    _exec("UPDATE systems SET extra = 'not json' WHERE id = ?", (b,))

    db.init_db()

    settings = db.get_settings()
    assert "scanEnableOmada" not in settings and "scanEnableAdguard" not in settings
    assert settings["scanTimeoutMs"] == 900
    row = _raw("SELECT extra, parentId, updatedAt FROM systems WHERE id = ?", (a,))[0]
    assert json.loads(row["extra"]) == {"unifi": {"z": 3}, "nameSource": "manual",
                                       "parentSource": "manual"}
    assert (row["parentId"], row["updatedAt"]) == (b, "U")
    assert _raw("SELECT extra FROM systems WHERE id = ?", (b,))[0]["extra"] == "not json"
    assert _raw("SELECT extra FROM systems WHERE id = ?", (c,))[0]["extra"] in (None, "")


def test_migration_survives_invalid_settings_blob(temp_db):
    _exec("INSERT OR REPLACE INTO settings (key, value) VALUES ('app', '{broken')")
    db.init_db()


def test_removed_scan_switches_not_in_defaults(temp_db):
    # The settings API model is derived from DEFAULT_SETTINGS, so these keys can no longer be stored.
    assert "scanEnableOmada" not in db.get_settings() and "scanEnableAdguard" not in db.get_settings()
