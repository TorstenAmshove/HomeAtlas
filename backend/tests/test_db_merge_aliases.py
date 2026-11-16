def _mk(db, key, ip, mac="", **kw):
    return db.create_system({"name": kw.pop("name", ip), "ip": ip, "mac": mac, "discoveryKey": key,
                             "discovered": 1, **kw})


def test_merge_records_aliases(temp_db):
    b = _mk(temp_db, "mac:aa", "10.0.0.1", "aa")
    a = _mk(temp_db, "ip:192.168.1.1", "192.168.1.1", "bb")
    temp_db.merge_systems(b["id"], a["id"])
    aliases = {x["aliasKey"]: x for x in temp_db.list_aliases(b["id"])}
    assert set(aliases) == {"ip:192.168.1.1", "mac:bb"}
    assert aliases["mac:bb"]["ip"] == "192.168.1.1" and aliases["mac:bb"]["mac"] == "bb"


def test_merge_keeps_accounts_and_history(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1")
    a = _mk(temp_db, "k:a", "10.0.0.2")
    acc = temp_db.create_account({"systemId": a["id"], "label": "x", "category": "login"})
    temp_db.record_monitor_state(a["id"], "offline", "d")
    temp_db.add_device_error_event(a["id"], "error", "boom")
    temp_db.merge_systems(b["id"], a["id"])
    assert temp_db.list_accounts(b["id"])[0]["id"] == acc["id"]
    assert temp_db.list_device_error_events(b["id"])
    with temp_db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM monitorEvents WHERE systemId = ?", (b["id"],)).fetchone()[0] == 1


def test_merge_without_discovery_key_adds_no_empty_alias(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1")
    a = temp_db.create_system({"name": "hand", "ip": "10.0.0.2"})
    temp_db.merge_systems(b["id"], a["id"])
    assert temp_db.list_aliases(b["id"]) == []


def test_rescan_with_alias_key_does_not_recreate(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1")
    a = _mk(temp_db, "ip:192.168.1.1", "192.168.1.1")
    temp_db.merge_systems(b["id"], a["id"])
    system, created = temp_db.upsert_discovered_system({"discoveryKey": "ip:192.168.1.1", "ip": "192.168.1.9"})
    assert created is False and system["id"] == b["id"]
    assert len(temp_db.list_systems()) == 1
    assert system["discoveryKey"] == "k:b" and system["ip"] == "10.0.0.1"


def test_rescan_with_alias_updates_alias_ip(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1")
    a = _mk(temp_db, "ip:192.168.1.1", "192.168.1.1")
    temp_db.merge_systems(b["id"], a["id"])
    temp_db.upsert_discovered_system({"discoveryKey": "ip:192.168.1.1", "ip": "192.168.1.9"})
    assert temp_db.list_aliases(b["id"])[0]["ip"] == "192.168.1.9"


def test_rescan_with_only_alias_mac_does_not_duplicate(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1", "aa")
    a = _mk(temp_db, "k:a", "192.168.1.1", "bb")
    temp_db.merge_systems(b["id"], a["id"])
    # Different key scheme, same MAC as the merged-away row.
    _, created = temp_db.upsert_discovered_system({"discoveryKey": "other", "ip": "192.168.1.1", "mac": "bb"})
    assert created is False and len(temp_db.list_systems()) == 1


def test_transitive_aliases_survive_second_merge(temp_db):
    a = _mk(temp_db, "k:a", "10.0.0.1")
    b = _mk(temp_db, "k:b", "10.0.0.2")
    c = _mk(temp_db, "k:c", "10.0.0.3")
    temp_db.merge_systems(b["id"], a["id"])
    temp_db.merge_systems(c["id"], b["id"])
    assert {x["aliasKey"] for x in temp_db.list_aliases(c["id"])} == {"k:a", "k:b"}


def test_delete_system_removes_aliases_and_dismissals(temp_db):
    b = _mk(temp_db, "k:b", "10.0.0.1")
    a = _mk(temp_db, "k:a", "10.0.0.2")
    c = _mk(temp_db, "k:c", "10.0.0.3")
    temp_db.merge_systems(b["id"], a["id"])
    temp_db.dismiss_duplicate(b["id"], c["id"])
    temp_db.delete_system(b["id"])
    with temp_db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM systemAliases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM duplicateDismissals").fetchone()[0] == 0
