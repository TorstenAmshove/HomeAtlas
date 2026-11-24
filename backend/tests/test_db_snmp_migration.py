"""init_db removes SNMP accounts and printer-supply/SNMP facts (issue #228)."""
import json

from app import db
from app.db._core import _conn


def _extra(system_id):
    with _conn() as conn:
        raw = conn.execute("SELECT extra FROM systems WHERE id = ?", (system_id,)).fetchone()["extra"]
    return json.loads(raw)


def test_init_db_removes_snmp_accounts_only(temp_db):
    system = db.create_system({"kind": "switch", "name": "S", "ip": "10.0.0.2"})
    snmp = db.create_account({"systemId": system["id"], "label": "s", "category": "snmp"})
    other = db.create_account({"systemId": system["id"], "label": "l", "category": "login"})

    db.init_db()
    db.init_db()

    assert db.get_account(snmp["id"]) is None
    assert db.get_account(other["id"])["category"] == "login"


def test_init_db_cleans_extra_probe_and_printer_supplies(temp_db):
    printer = db.create_system({"kind": "printer", "name": "P", "ip": "10.0.0.3"})
    only_snmp = db.create_system({"kind": "switch", "name": "S", "ip": "10.0.0.4"})
    broken = db.create_system({"kind": "switch", "name": "B", "ip": "10.0.0.5"})
    with _conn() as conn:
        conn.execute("UPDATE systems SET extra = ?, updatedAt = 'x' WHERE id = ?", (json.dumps({
            "printerSupplies": [{"name": "Toner"}],
            "keep": 1,
            "probe": {"snmp:a": {"ok": True}, "ssh:a": {"ok": True}, "ha:a": {"ok": True}},
        }), printer["id"]))
        conn.execute("UPDATE systems SET extra = ? WHERE id = ?",
                     (json.dumps({"probe": {"snmp:a": {"ok": True}}}), only_snmp["id"]))
        conn.execute("UPDATE systems SET extra = ? WHERE id = ?", ("{kaputt", broken["id"]))

    db.init_db()
    db.init_db()

    extra = _extra(printer["id"])
    assert "printerSupplies" not in extra and extra["keep"] == 1
    assert set(extra["probe"]) == {"ssh:a", "ha:a"}
    assert _extra(only_snmp["id"]) == {"probe": {}}
    with _conn() as conn:
        assert conn.execute("SELECT updatedAt FROM systems WHERE id = ?",
                            (printer["id"],)).fetchone()["updatedAt"] == "x"
        assert conn.execute("SELECT extra FROM systems WHERE id = ?",
                            (broken["id"],)).fetchone()["extra"] == "{kaputt"
