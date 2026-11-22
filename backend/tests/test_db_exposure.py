import sqlite3

from app import db


def _fact(key, **data):
    return {"kind": "caddy_site", "key": key, "data": {"host": key, **data}}


def test_replace_only_on_success_and_stale_keeps_facts(temp_db):
    db.replace_exposure_facts("caddy", "a1", [_fact("app1.example.net")])
    first = db.list_exposure_facts()[0]["firstSeen"]
    db.mark_exposure_facts_stale("caddy", "a1")
    rows = db.list_exposure_facts()
    assert len(rows) == 1 and rows[0]["stale"] == 1 and rows[0]["data"]["host"] == "app1.example.net"
    # successful empty read replaces (legitimately no sites), firstSeen survives for known facts
    db.replace_exposure_facts("caddy", "a1", [_fact("app1.example.net")])
    row = db.list_exposure_facts()[0]
    assert row["stale"] == 0 and row["firstSeen"] == first
    db.replace_exposure_facts("caddy", "a1", [])
    assert db.list_exposure_facts() == []


def test_other_accounts_untouched_and_delete_with_account(temp_db):
    acc = db.create_account({"label": "Caddy", "category": "exposure_caddy"})
    db.replace_exposure_facts("caddy", acc["id"], [_fact("a.example.net")])
    db.replace_exposure_facts("caddy", "other", [_fact("b.example.net")])
    db.replace_exposure_facts("caddy", acc["id"], [])
    assert [f["key"] for f in db.list_exposure_facts()] == ["b.example.net"]
    db.replace_exposure_facts("caddy", acc["id"], [_fact("a.example.net")])
    db.delete_account(acc["id"])
    assert [f["key"] for f in db.list_exposure_facts()] == ["b.example.net"]
    db.delete_exposure_facts(source="caddy")
    assert db.list_exposure_facts() == []


def test_migration_on_existing_db_is_idempotent(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    sqlite3.connect(path).execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)").connection.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    db.init_db()
    assert db.list_exposure_facts() == []


def test_migration_removes_unifi_classic_accounts(temp_db):
    old = temp_db.create_account({"label": "alt", "category": "unifi_classic"})
    keep = temp_db.create_account({"label": "neu", "category": "unifi"})
    temp_db.replace_exposure_facts("unifi_classic", old["id"], [_fact("scan")])
    temp_db.sync_network_resources(old["id"], [{"kind": "wan", "source": "unifi", "siteExternalId": "s",
                                                "externalId": "w", "name": "w"}], [])
    temp_db.init_db()
    assert [a["id"] for a in temp_db.list_accounts()] == [keep["id"]]
    assert temp_db.list_exposure_facts() == []
    assert all(not r["active"] for r in temp_db.list_network_resources("wan"))
    temp_db.init_db()  # idempotent
    assert [a["id"] for a in temp_db.list_accounts()] == [keep["id"]]
