"""'Critical implies monitored' is a one-time default at marking, not a rule (issue #131)."""
import asyncio

from app import db, monitor


def _dev(name="A", **kw):
    return db.create_system({"name": name, **kw})


def _mon(system_id):
    return db.get_system(system_id)["monitored"]


def test_marking_critical_enables_monitoring_with_address(temp_db):
    a = _dev(ip="10.0.0.1")
    b = _dev("B", hostname="b.lan")
    db.update_system(a["id"], {"importance": "critical"})
    db.update_system(b["id"], {"importance": "critical"})
    assert _mon(a["id"]) == 1 and _mon(b["id"]) == 1


def test_marking_critical_without_address_leaves_monitored(temp_db):
    a = _dev()
    db.update_system(a["id"], {"importance": "critical"})
    assert _mon(a["id"]) == 0
    db.update_system(a["id"], {"ip": "10.0.0.2"})
    assert _mon(a["id"]) == 0


def test_create_critical_with_address_enables_monitoring(temp_db):
    assert _dev(ip="10.0.0.3", importance="critical")["monitored"] == 1
    assert _dev("N", importance="critical")["monitored"] == 0


def test_explicit_monitored_zero_wins_over_transition(temp_db):
    a = _dev(ip="10.0.0.1", monitored=1)
    db.update_system(a["id"], {"monitored": 0})
    db.update_system(a["id"], {"importance": "critical", "monitored": 1})
    db.update_system(a["id"], {"importance": "normal"})
    db.update_system(a["id"], {"importance": "critical", "monitored": 0})
    assert _mon(a["id"]) == 0


def test_patch_other_field_keeps_opt_out(temp_db):
    a = _dev(ip="10.0.0.1")
    db.update_system(a["id"], {"importance": "critical"})
    db.update_system(a["id"], {"monitored": 0})
    db.update_system(a["id"], {"name": "X", "importance": "critical", "monitored": 0})
    assert _mon(a["id"]) == 0


def test_removing_critical_keeps_monitored(temp_db):
    a = _dev(ip="10.0.0.1")
    db.update_system(a["id"], {"importance": "critical"})
    db.update_system(a["id"], {"importance": "normal"})
    assert _mon(a["id"]) == 1


def test_remarking_critical_enables_again(temp_db):
    a = _dev(ip="10.0.0.1")
    db.update_system(a["id"], {"importance": "critical"})
    db.update_system(a["id"], {"monitored": 0})
    db.update_system(a["id"], {"importance": "normal"})
    db.update_system(a["id"], {"importance": "critical"})
    assert _mon(a["id"]) == 1


def test_opt_out_survives_patch_monitor_round_and_rescan(temp_db, monkeypatch):
    a = _dev(ip="10.0.0.1")
    db.update_system(a["id"], {"importance": "critical"})
    db.update_system(a["id"], {"monitored": 0})
    db.update_system(a["id"], {"purpose": "x"})
    assert _mon(a["id"]) == 0

    async def fake_check(system, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("unmonitored device was polled")

    monkeypatch.setattr(monitor, "check_system", fake_check, raising=False)
    asyncio.run(monitor.Monitor().run_once())
    db.upsert_discovered_system({"ip": "10.0.0.1", "discoveryKey": a["discoveryKey"] or "", "name": "A"})
    assert _mon(a["id"]) == 0


def test_scan_promotion_enables_once(temp_db):
    row = db.create_system({"name": "S", "ip": "10.0.0.5", "discoveryKey": "ip:10.0.0.5", "discovered": 1})
    found = {"name": "S", "ip": "10.0.0.5", "discoveryKey": "ip:10.0.0.5", "importance": "critical"}
    db.upsert_discovered_system(found)
    assert _mon(row["id"]) == 1
    db.update_system(row["id"], {"monitored": 0})
    db.upsert_discovered_system(found)
    assert _mon(row["id"]) == 0
    conf = db.create_system({"name": "C", "ip": "10.0.0.6", "discoveryKey": "ip:10.0.0.6", "confirmed": 1})
    db.upsert_discovered_system({"name": "C", "ip": "10.0.0.6", "discoveryKey": "ip:10.0.0.6",
                                 "importance": "critical"})
    assert db.get_system(conf["id"])["importance"] == "normal" and _mon(conf["id"]) == 0


def test_merge_taking_critical_importance_enables_monitoring(temp_db):
    keep = _dev("K", ip="10.0.0.7", discoveryKey="k:1")
    remove = _dev("R", ip="10.0.0.8", discoveryKey="k:2", importance="critical")
    db.update_system(remove["id"], {"monitored": 0})
    db.merge_systems(keep["id"], remove["id"])
    got = db.get_system(keep["id"])
    assert got["importance"] == "critical" and got["monitored"] == 1


def test_unticked_box_in_same_save_wins_when_unchanged(temp_db):
    """Form flow: device not monitored, user marks it critical (box gets ticked automatically),
    unticks it again and saves -> PATCH {importance: critical, monitored: 0}; 0 equals the stored
    value but is still the user's explicit choice."""
    a = _dev(ip="10.0.0.1")
    assert _mon(a["id"]) == 0
    db.update_system(a["id"], {"importance": "critical", "monitored": 0})
    assert _mon(a["id"]) == 0


def test_monitored_none_does_not_block_default(temp_db):
    a = _dev(ip="10.0.0.1")
    db.update_system(a["id"], {"importance": "critical", "monitored": None})
    assert _mon(a["id"]) == 1
