import sqlite3

from app import db


def _fact(key, **data):
    return {"kind": "policy", "key": key, "data": {"name": key, **data}}


def test_replace_keeps_first_seen(temp_db):
    db.replace_firewall_facts("unifi", "a1", [_fact("p1")])
    first = db.list_firewall_facts()[0]["firstSeen"]
    db.replace_firewall_facts("unifi", "a1", [_fact("p1"), _fact("p2")])
    rows = {r["key"]: r for r in db.list_firewall_facts()}
    assert rows["p1"]["firstSeen"] == first and rows["p2"]["data"]["name"] == "p2"
    db.replace_firewall_facts("unifi", "a1", [])
    assert db.list_firewall_facts() == []


def test_failed_read_marks_stale(temp_db):
    db.replace_firewall_facts("unifi", "a1", [_fact("p1")])
    db.mark_firewall_facts_stale("unifi", "a1")
    rows = db.list_firewall_facts()
    assert len(rows) == 1 and rows[0]["stale"] == 1
    db.replace_firewall_facts("unifi", "a1", [_fact("p1")])
    assert db.list_firewall_facts()[0]["stale"] == 0


def test_account_delete_removes_facts(temp_db):
    acc = db.create_account({"label": "UniFi", "category": "unifi"})
    db.replace_firewall_facts("unifi", acc["id"], [_fact("p1")])
    db.replace_firewall_facts("unifi", "other", [_fact("p2")])
    db.delete_account(acc["id"])
    assert [f["key"] for f in db.list_firewall_facts()] == ["p2"]


def test_prune_removed_accounts_and_delete_source(temp_db):
    db.replace_firewall_facts("unifi", "a1", [_fact("p1")])
    db.replace_firewall_facts("unifi", "a2", [_fact("p2")])
    db.prune_firewall_facts("unifi", ["a2"])
    assert [f["key"] for f in db.list_firewall_facts()] == ["p2"]
    db.delete_firewall_facts(source="unifi")
    assert db.list_firewall_facts() == []


def test_migration_on_existing_db(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    sqlite3.connect(path).execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)").connection.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    db.init_db()
    assert db.list_firewall_facts() == []
