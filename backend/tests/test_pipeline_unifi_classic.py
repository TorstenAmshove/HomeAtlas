import asyncio

from app import pipeline

KEY = "key-secret-12345"


def _scan(db, monkeypatch):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline.crypto, "decrypt", lambda value: KEY)
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


def test_wan_ips_attach_to_existing_rows_only_when_counts_match(temp_db):
    def res(ext):
        return {"kind": "wan", "source": "unifi", "siteExternalId": "s", "externalId": ext, "name": ext, "facts": {}}

    temp_db.sync_network_resources("a", [res("w1")], [("s", "wan")])
    assert temp_db.set_wan_ips("a", ["203.0.113.7", "198.51.100.1"]) == 0
    assert temp_db.set_wan_ips("a", ["203.0.113.7"]) == 1
    rows = temp_db.list_network_resources("wan")
    assert len(rows) == 1 and rows[0]["facts"]["ip"] == "203.0.113.7"
