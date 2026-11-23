"""GET /api/dashboard: removed unused fields stay gone, remaining counts match direct SQL (issue #85)."""
import asyncio
import sqlite3

from app import db
from app.routes import overview


def _dashboard():
    return asyncio.run(overview.dashboard({"id": "x"}))


def _seed():
    db.create_system({"name": "A", "kind": "server", "ip": "192.168.1.2", "status": "online",
                      "importance": "critical", "descriptionMd": "doc"})
    db.create_system({"name": "B", "kind": "pc", "status": "online", "importance": "normal"})
    db.create_system({"name": "C", "kind": "mobile", "status": "offline", "importance": "normal"})
    db.create_system({"name": "D", "kind": "iot", "status": "unknown", "importance": "low"})
    db.create_account({"label": "Konto", "category": "login"})


def test_removed_fields_absent(temp_db):
    _seed()
    d = _dashboard()
    for key in ("recentlyChanged", "setupCompleted"):
        assert key not in d
    assert set(d["counts"]) == {"total", "online", "critical", "accounts"}


def test_counts_match_sql(temp_db):
    _seed()
    d = _dashboard()
    c = sqlite3.connect(db.DB_PATH)

    def q(sql):
        return c.execute(sql).fetchone()[0]

    assert d["counts"] == {
        "total": q("SELECT COUNT(*) FROM systems"),
        "online": q("SELECT COUNT(*) FROM systems WHERE status='online'"),
        "critical": q("SELECT COUNT(*) FROM systems WHERE importance='critical'"),
        "accounts": q("SELECT COUNT(*) FROM accounts"),
    }
    assert d["counts"] == {"total": 4, "online": 2, "critical": 1, "accounts": 1}
    for key in ("homeName", "byKind", "kindLabels", "criticalSystems", "monitorIntervalSeconds",
                "monitorEnabled", "lastScan", "llmConfigured"):
        assert key in d
    assert "monitorPortsEffective" in d["criticalSystems"][0]


def test_empty_db(temp_db):
    d = _dashboard()
    assert d["counts"] == {"total": 0, "online": 0, "critical": 0, "accounts": 0}
    assert d["byKind"] == {}


def test_last_scan_is_slim(temp_db):
    assert _dashboard()["lastScan"] is None
    old = db.create_scan("192.168.1.0/24")
    db.finish_scan(old, "completed", {"found": 1})
    with sqlite3.connect(db.DB_PATH) as c:  # startedAt has second resolution; make "old" older
        c.execute("UPDATE scans SET startedAt = '2020-01-01T00:00:00Z' WHERE id = ?", (old,))
    new = db.create_scan("192.168.1.0/24")
    db.update_scan(new, log_line="Gerät fritz.box gefunden")
    d = _dashboard()
    assert set(d["lastScan"]) == {"startedAt", "finishedAt", "status"}
    assert d["lastScan"]["finishedAt"] is None and d["lastScan"]["status"] == "running"
    db.finish_scan(new, "completed", {"found": 2})
    assert set(_dashboard()["lastScan"]) == {"startedAt", "finishedAt", "status"}
    # other consumers (docs.py, pipeline.py) still get the full row
    full = db.latest_scan()
    assert "log" in full and "summary" in full
