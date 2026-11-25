import asyncio

from app import pipeline

KEY = "key-secret-12345"


def _scan(db, monkeypatch):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline.crypto, "decrypt_strict", lambda value: KEY)
    asyncio.run(pipeline.run_full_scan(db.create_scan("test")))


def _account(db, **extra):
    system = db.create_system({"name": "UCG", "ip": "192.0.2.1", "kind": "router"})
    account = db.create_account({"label": "UniFi", "category": "unifi", "systemId": system["id"], "allowProbe": 1,
                                 "url": "https://192.0.2.1", **extra})
    return account, system


def _ok(calls):
    async def probe(url, key, account_id, system_id):
        calls.append(key)
        return {"ok": True, "error": "", "wanIps": [],
                "forwards": [{"kind": "portforward_scan", "key": "scan", "data": {"count": 0}}]}
    return probe


def test_unifi_account_with_key_is_read_and_disabled_without_opt_in(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    calls: list = []
    monkeypatch.setattr(pipeline.unifi_classic_probe, "probe", _ok(calls))
    monkeypatch.setattr(pipeline.unifi_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": True, "error": "", "warnings": [], "systems": [], "resources": [], "completeScopes": []}))
    _scan(temp_db, monkeypatch)
    assert calls == [KEY] and [r["source"] for r in temp_db.list_exposure_facts()] == ["unifi_classic"]
    temp_db.update_account(account["id"], {"allowProbe": 0})
    _scan(temp_db, monkeypatch)
    assert calls == [KEY] and temp_db.list_exposure_facts() == []


def test_failure_marks_stale_without_key_and_other_account_runs(temp_db, monkeypatch):
    account, system = _account(temp_db)
    other, _ = _account(temp_db)
    seen: list = []

    async def probe(url, key, account_id, system_id):
        seen.append(account_id)
        if account_id == account["id"]:
            raise RuntimeError(KEY)
        return await _ok([])(url, key, account_id, system_id)

    monkeypatch.setattr(pipeline.unifi_classic_probe, "probe", probe)
    monkeypatch.setattr(pipeline.unifi_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": False, "error": "x", "warnings": [], "systems": [], "resources": [], "completeScopes": []}))
    _scan(temp_db, monkeypatch)
    assert set(seen) == {account["id"], other["id"]}
    assert [r["sourceAccountId"] for r in temp_db.list_exposure_facts()] == [other["id"]]
    assert all(KEY not in e["message"] for e in temp_db.list_device_error_events(system["id"]))


def test_wan_status_attaches_by_name_and_clears_inactive(temp_db):
    def res(ext, name):
        return {"kind": "wan", "source": "unifi", "siteExternalId": "s", "externalId": ext, "name": name, "facts": {}}

    temp_db.sync_network_resources("a", [res("w1", "Reserve"), res("w2", "DSL")], [("s", "wan")])
    wans = [{"name": "DSL", "type": "dhcp", "active": True, "ip": "8.8.4.4", "interfaceIp": "192.168.178.20"},
            {"name": "Reserve", "type": "dhcp", "active": False, "ip": "", "interfaceIp": ""}]
    assert temp_db.set_wan_status("a", wans) == 2
    rows = {r["name"]: r["facts"] for r in temp_db.list_network_resources("wan")}
    assert rows["DSL"]["ip"] == "8.8.4.4" and rows["DSL"]["active"] is True
    assert "ip" not in rows["Reserve"] and rows["Reserve"]["active"] is False
    temp_db.set_wan_status("a", [{"name": "DSL", "type": "dhcp", "active": False, "ip": "", "interfaceIp": ""}])
    assert "ip" not in {r["name"]: r["facts"] for r in temp_db.list_network_resources("wan")}["DSL"]


SW, AP, TV, PHONE = "aa:bb:cc:00:00:10", "aa:bb:cc:00:00:20", "aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"


def _devices(db):
    sw = db.create_system({"name": "Switch Flur", "ip": "192.0.2.2", "kind": "switch", "mac": SW})
    ap = db.create_system({"name": "AP Wohnzimmer", "ip": "192.0.2.3", "kind": "accesspoint", "mac": AP})
    tv = db.create_system({"name": "Fernseher", "ip": "192.0.2.4", "kind": "tv", "mac": TV.upper()})
    phone = db.create_system({"name": "Handy", "ip": "192.0.2.5", "kind": "phone", "mac": PHONE})
    return sw, ap, tv, phone


def _client(mac, **kw):
    return {"site": "default", "mac": mac, "wired": False, "swMac": "", "swPort": None, "apMac": "",
            "essid": "", **kw}


WIRED_C = _client(TV, wired=True, swMac=SW, swPort=5)
WIFI_C = _client(PHONE, apMac=AP, essid="Zuhause")


def _scan_with(db, monkeypatch, clients_ref, warnings=None):
    async def probe(url, key, account_id, system_id):
        result = await _ok([])(url, key, account_id, system_id)
        if clients_ref is None:
            return {"ok": False, "error": "x", "forwards": [], "warnings": []}
        return {**result, "clients": clients_ref, "warnings": warnings or []}

    monkeypatch.setattr(pipeline.unifi_classic_probe, "probe", probe)
    monkeypatch.setattr(pipeline.unifi_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": True, "error": "", "warnings": [], "systems": [], "resources": [], "completeScopes": []}))
    _scan(db, monkeypatch)


def _conn(db, system):
    return ((db.get_system(system["id"]).get("extra") or {}).get("unifi") or {}).get("connection")


def test_connection_wired_and_wifi(temp_db, monkeypatch):
    _account(temp_db)
    sw, ap, tv, phone = _devices(temp_db)
    _scan_with(temp_db, monkeypatch, [WIRED_C, WIFI_C])
    wired, wifi = _conn(temp_db, tv), _conn(temp_db, phone)
    assert wired["type"] == "wired" and wired["systemId"] == sw["id"] and wired["port"] == 5 and "ssid" not in wired
    assert wifi["type"] == "wifi" and wifi["systemId"] == ap["id"] and wifi["ssid"] == "Zuhause" and "port" not in wifi


def test_connection_has_only_allowlisted_keys(temp_db, monkeypatch):
    _account(temp_db)
    _, _, tv, _ = _devices(temp_db)
    _scan_with(temp_db, monkeypatch, [{**WIRED_C, "name": "Geheim", "ip": "1.2.3.4"}])
    assert set(_conn(temp_db, tv)) <= {"type", "systemId", "deviceMac", "port", "ssid", "site", "accountId"}
    assert "Geheim" not in str(temp_db.get_system(tv["id"])["extra"])


def test_unknown_client_creates_no_system(temp_db, monkeypatch):
    _devices(temp_db)
    before = len(temp_db.list_systems())
    pipeline._link_unifi_connections("a", [_client("aa:bb:cc:99:99:99", wired=True, swMac=SW, swPort=1)])
    assert len(temp_db.list_systems()) == before


def test_manual_parent_untouched_by_connections(temp_db, monkeypatch):
    sw, ap, tv, _ = _devices(temp_db)
    temp_db.update_system(tv["id"], {"parentId": ap["id"], "extra": {"parentSource": "manual"}})
    pipeline._link_unifi_connections("a", [WIRED_C])
    current = temp_db.get_system(tv["id"])
    assert current["parentId"] == ap["id"] and current["extra"]["parentSource"] == "manual"
    assert _conn(temp_db, tv)["systemId"] == sw["id"]


def test_connection_removed_when_client_gone_only_after_successful_read(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    _, _, tv, _ = _devices(temp_db)
    _scan_with(temp_db, monkeypatch, [WIRED_C])
    assert _conn(temp_db, tv)
    _scan_with(temp_db, monkeypatch, [WIRED_C], warnings=["Client-Zuordnung nicht lesbar (ValueError)."])
    assert _conn(temp_db, tv)
    _scan_with(temp_db, monkeypatch, [])
    assert _conn(temp_db, tv) is None


def test_failed_or_disabled_classic_scan_keeps_connection(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    _, _, tv, _ = _devices(temp_db)
    _scan_with(temp_db, monkeypatch, [WIRED_C])
    _scan_with(temp_db, monkeypatch, None)
    assert _conn(temp_db, tv)
    temp_db.update_account(account["id"], {"allowProbe": 0})
    _scan_with(temp_db, monkeypatch, [])
    assert _conn(temp_db, tv)


def test_wired_to_wifi_replaces_connection(temp_db, monkeypatch):
    _, ap, tv, _ = _devices(temp_db)
    pipeline._link_unifi_connections("a", [WIRED_C])
    pipeline._link_unifi_connections("a", [_client(TV, apMac=AP, essid="Zuhause")])
    conn = _conn(temp_db, tv)
    assert conn["type"] == "wifi" and "port" not in conn and conn["systemId"] == ap["id"]


def test_unresolved_switch_wired_no_connection_wifi_ssid_only(temp_db, monkeypatch):
    _, _, tv, phone = _devices(temp_db)
    pipeline._link_unifi_connections("a", [_client(TV, wired=True, swMac="aa:bb:cc:77:77:77", swPort=2),
                                           _client(PHONE, apMac="aa:bb:cc:77:77:78", essid="Zuhause")])
    assert _conn(temp_db, tv) is None
    assert "systemId" not in _conn(temp_db, phone) and _conn(temp_db, phone)["ssid"] == "Zuhause"


def test_second_scan_is_idempotent(temp_db, monkeypatch):
    _account(temp_db)
    _, _, tv, _ = _devices(temp_db)
    _scan_with(temp_db, monkeypatch, [WIRED_C])
    first = temp_db.get_system(tv["id"])["updatedAt"]
    calls = []
    real = pipeline.db.update_system
    monkeypatch.setattr(pipeline.db, "update_system", lambda sid, patch: calls.append(patch) or real(sid, patch))
    pipeline._link_unifi_connections(_conn(temp_db, tv)["accountId"], [WIRED_C])
    assert calls == [] and temp_db.get_system(tv["id"])["updatedAt"] == first


def test_same_client_in_two_sites_first_wins(temp_db, monkeypatch):
    _, _, tv, _ = _devices(temp_db)
    pipeline._link_unifi_connections("a", [WIRED_C, {**WIRED_C, "site": "b2", "swPort": 9}])
    assert _conn(temp_db, tv)["port"] == 5


def test_two_accounts_cleanup_isolated(temp_db):
    _, _, tv, phone = _devices(temp_db)
    pipeline._link_unifi_connections("a", [WIRED_C])
    pipeline._link_unifi_connections("b", [WIFI_C])
    pipeline._link_unifi_connections("b", [])
    assert _conn(temp_db, tv)["accountId"] == "a" and _conn(temp_db, phone) is None


def test_duplicate_mac_is_not_matched(temp_db):
    _, _, tv, _ = _devices(temp_db)
    temp_db.create_system({"name": "Doppelt", "ip": "192.0.2.9", "kind": "tv", "mac": TV})
    assert pipeline._link_unifi_connections("a", [WIRED_C]) == 0


def _sw_ports(mac=SW, vlan=10, site="default"):
    port = {"port": 1, "name": "P1", "profile": "All", "native": {"vlan": vlan, "name": "Default", "known": True},
            "tagged": {"mode": "all", "vlans": [], "excluded": []}}
    return {"site": site, "mac": mac, "ports": [port]}


def _ports(db, system):
    return ((db.get_system(system["id"]).get("extra") or {}).get("unifi") or {}).get("ports")


def _scan_ports(db, monkeypatch, switches, ports_ok=True):
    async def probe(url, key, account_id, system_id):
        result = await _ok([])(url, key, account_id, system_id)
        return {**result, "clients": [], "warnings": [], "switches": switches, "portsOk": ports_ok}

    monkeypatch.setattr(pipeline.unifi_classic_probe, "probe", probe)
    monkeypatch.setattr(pipeline.unifi_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": True, "error": "", "warnings": [], "systems": [], "resources": [], "completeScopes": []}))
    _scan(db, monkeypatch)


def test_switch_ports_stored(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    sw, _, tv, _ = _devices(temp_db)
    _scan_ports(temp_db, monkeypatch, [_sw_ports(SW.upper())])
    stored = _ports(temp_db, sw)
    assert stored["accountId"] == account["id"] and stored["site"] == "default"
    assert stored["ports"][0]["native"]["vlan"] == 10 and _ports(temp_db, tv) is None


def test_switch_ports_replaced_each_scan(temp_db, monkeypatch):
    _account(temp_db)
    sw, _, _, _ = _devices(temp_db)
    _scan_ports(temp_db, monkeypatch, [_sw_ports(vlan=10)])
    _scan_ports(temp_db, monkeypatch, [_sw_ports(vlan=20)])
    assert _ports(temp_db, sw)["ports"][0]["native"]["vlan"] == 20


def test_switch_ports_kept_on_partial_failure(temp_db, monkeypatch):
    _account(temp_db)
    sw, _, _, _ = _devices(temp_db)
    _scan_ports(temp_db, monkeypatch, [_sw_ports()])
    _scan_ports(temp_db, monkeypatch, [], ports_ok=False)
    assert _ports(temp_db, sw) is not None


def test_switch_ports_removed_when_switch_gone_after_full_read(temp_db, monkeypatch):
    _account(temp_db)
    sw, _, _, _ = _devices(temp_db)
    _scan_ports(temp_db, monkeypatch, [_sw_ports()])
    _scan_ports(temp_db, monkeypatch, [])
    assert _ports(temp_db, sw) is None


def test_switch_ports_other_account_untouched(temp_db):
    sw, _, _, _ = _devices(temp_db)
    pipeline._store_switch_ports("a", [_sw_ports()])
    pipeline._store_switch_ports("b", [])
    assert _ports(temp_db, sw)["accountId"] == "a"


def test_switch_without_inventory_device_creates_nothing(temp_db):
    before = len(temp_db.list_systems())
    assert pipeline._store_switch_ports("a", [_sw_ports("aa:bb:cc:99:99:99")]) == 0
    assert len(temp_db.list_systems()) == before
