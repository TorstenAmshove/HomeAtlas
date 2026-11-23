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
