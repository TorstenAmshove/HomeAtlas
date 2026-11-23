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


def _svc(port):
    return {"port": port, "service": f"s{port}", "explanation": ""}


def test_merge_keeps_extra_ports_and_services_of_removed_row(temp_db):
    keep = temp_db.create_system({"name": "UCG", "ip": "192.168.42.2", "confirmed": 1,
                                  "extra": {"probe": {"http:UCG": {"ok": True}}}})
    gone = _mk(temp_db, "mac:aa", "192.168.178.20", "aa", openPorts=[22, 443],
               services=[_svc(22), _svc(443)],
               extra={"unifi": {"name": "UCG Ultra"}, "probe": {"ssh:x": {"ok": True}}})
    merged = temp_db.merge_systems(keep["id"], gone["id"])
    assert merged["extra"]["unifi"] == {"name": "UCG Ultra"}
    assert set(merged["extra"]["probe"]) == {"http:UCG", "ssh:x"}
    assert merged["openPorts"] == [22, 443]
    assert [s["port"] for s in merged["services"]] == [22, 443]
    assert set(merged["extra"]["interfaces"]) == {"192.168.42.2", "192.168.178.20"}


def test_merge_same_ip_unites_ports(temp_db):
    keep = temp_db.create_system({"name": "hand", "ip": "10.0.0.1"})
    gone = _mk(temp_db, "mac:aa", "10.0.0.1", "aa", openPorts=[80], services=[_svc(80)])
    merged = temp_db.merge_systems(keep["id"], gone["id"])
    assert merged["openPorts"] == [80]
    assert merged["extra"]["interfaces"]["10.0.0.1"]["openPorts"] == [80]


def test_rescan_of_each_interface_keeps_the_others_ports(temp_db):
    keep = _mk(temp_db, "k:b", "10.0.0.1", openPorts=[443], services=[_svc(443)])
    gone = _mk(temp_db, "ip:192.168.1.1", "192.168.1.1", openPorts=[53], services=[_svc(53)])
    temp_db.merge_systems(keep["id"], gone["id"])
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "ip:192.168.1.1", "ip": "192.168.1.1", "openPorts": [53, 22],
         "services": [_svc(53), _svc(22)]})
    assert system["openPorts"] == [22, 53, 443]
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "k:b", "ip": "10.0.0.1", "openPorts": [443, 80], "services": [_svc(443), _svc(80)]})
    assert system["openPorts"] == [22, 53, 80, 443]
    assert system["extra"]["interfaces"]["192.168.1.1"]["openPorts"] == [53, 22]
    # The alias interface moved to a new address: the stale entry goes away.
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "ip:192.168.1.1", "ip": "192.168.1.9", "openPorts": [53], "services": [_svc(53)]})
    assert set(system["extra"]["interfaces"]) == {"10.0.0.1", "192.168.1.9"}
    assert system["openPorts"] == [53, 80, 443]


def test_alias_hit_on_row_merged_before_interfaces_existed(temp_db):
    keep = _mk(temp_db, "k:b", "10.0.0.1", openPorts=[443], services=[_svc(443)])
    gone = _mk(temp_db, "ip:192.168.1.1", "192.168.1.1")
    temp_db.merge_systems(keep["id"], gone["id"])
    with temp_db._conn() as conn:  # state as left by the old merge: no interfaces bookkeeping
        conn.execute("UPDATE systems SET extra = '{}' WHERE id = ?", (keep["id"],))
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "ip:192.168.1.1", "ip": "192.168.1.1", "openPorts": [53], "services": [_svc(53)]})
    assert system["openPorts"] == [53, 443]


def test_finding_without_ports_does_not_wipe_scanned_ports(temp_db):
    row = _mk(temp_db, "mac:aa", "10.0.0.5", "aa", openPorts=[8006], services=[_svc(8006)])
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "mac:aa", "ip": "10.0.0.5", "mac": "aa", "extra": {"unifi": {"name": "pve"}}})
    assert system["id"] == row["id"]
    assert system["openPorts"] == [8006] and system["services"][0]["port"] == 8006
    system, _ = temp_db.upsert_discovered_system(
        {"discoveryKey": "mac:aa", "ip": "10.0.0.5", "mac": "aa", "openPorts": [], "services": []})
    assert system["openPorts"] == []


def _count(db, table, system_id):
    with db._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE systemId = ?", (system_id,)).fetchone()[0]


def test_delete_system_removes_history_rows(temp_db):
    a = _mk(temp_db, "k:a", "10.0.0.1")
    other = _mk(temp_db, "k:o", "10.0.0.2")
    for s in (a, other):
        temp_db.save_device_config_version(s["id"], "cfg", "dummy-enc", "ssh")
        temp_db.add_device_error_event(s["id"], "error", "boom")
        temp_db.record_monitor_state(s["id"], "offline", "d")
    temp_db.delete_system(a["id"])
    for table in ("deviceConfigVersions", "deviceErrorEvents", "monitorEvents"):
        assert _count(temp_db, table, a["id"]) == 0
        assert _count(temp_db, table, other["id"]) == 1


def test_merge_keep_child_of_removed_gets_removed_parent(temp_db):
    grand = _mk(temp_db, "k:g", "10.0.0.3")
    keep = _mk(temp_db, "k:k", "10.0.0.1")
    remove = _mk(temp_db, "k:r", "10.0.0.2")
    temp_db.update_system(remove["id"], {"parentId": grand["id"]})
    temp_db.update_system(keep["id"], {"parentId": remove["id"]})
    child = _mk(temp_db, "k:c", "10.0.0.4")
    temp_db.update_system(child["id"], {"parentId": remove["id"]})
    merged = temp_db.merge_systems(keep["id"], remove["id"])
    assert merged["parentId"] == grand["id"]
    assert temp_db.get_system(child["id"])["parentId"] == keep["id"]


def test_merge_keep_child_of_removed_gets_null_without_grandparent(temp_db):
    keep = _mk(temp_db, "k:k", "10.0.0.1")
    remove = _mk(temp_db, "k:r", "10.0.0.2")
    temp_db.update_system(keep["id"], {"parentId": remove["id"]})
    merged = temp_db.merge_systems(keep["id"], remove["id"])
    assert not merged["parentId"]


def test_merge_removed_child_of_keep_leaves_no_dangling_parent(temp_db):
    keep = _mk(temp_db, "k:k", "10.0.0.1")
    remove = _mk(temp_db, "k:r", "10.0.0.2")
    temp_db.update_system(remove["id"], {"parentId": keep["id"]})
    merged = temp_db.merge_systems(keep["id"], remove["id"])
    assert merged["parentId"] != keep["id"]
