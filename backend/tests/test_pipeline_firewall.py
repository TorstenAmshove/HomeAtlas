import asyncio

from app import pipeline

KEY = "key-secret-12345"
FACT = {"kind": "zone", "key": "zone:default:z1", "data": {"id": "z1", "name": "DMZ"}}


def _scan(db, monkeypatch, firewall=True):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline.crypto, "decrypt", lambda value: KEY)
    monkeypatch.setattr(pipeline.unifi_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": False, "error": "x", "warnings": [], "systems": [], "resources": [], "completeScopes": []}))
    monkeypatch.setattr(pipeline.unifi_classic_probe, "probe", lambda *a, **k: asyncio.sleep(0, {
        "ok": True, "error": "", "wanIps": [], "forwards": []}))
    db.update_settings({"scanEnableFirewallUnifi": firewall})
    asyncio.run(pipeline.run_full_scan(db.create_scan("test")))


def _account(db):
    system = db.create_system({"name": "UCG", "ip": "192.0.2.1", "kind": "router"})
    account = db.create_account({"label": "UniFi", "category": "unifi", "systemId": system["id"], "allowProbe": 1,
                                 "url": "https://192.0.2.1"})
    return account, system


def _ok(calls):
    async def probe(url, key, account_id, system_id):
        calls.append(key)
        return {"ok": True, "error": "", "facts": [FACT]}
    return probe


def test_default_is_off(temp_db):
    assert temp_db.get_settings()["scanEnableFirewallUnifi"] is False


def test_unifi_success_replaces_facts(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    calls: list = []
    monkeypatch.setattr(pipeline.firewall_unifi, "probe", _ok(calls))
    _scan(temp_db, monkeypatch)
    rows = temp_db.list_firewall_facts()
    assert calls == [KEY] and [(r["source"], r["sourceAccountId"], r["stale"]) for r in rows] == [("unifi", account["id"], 0)]


def test_failure_marks_stale_and_event_without_key(temp_db, monkeypatch):
    account, system = _account(temp_db)
    monkeypatch.setattr(pipeline.firewall_unifi, "probe", _ok([]))
    _scan(temp_db, monkeypatch)

    async def boom(url, key, account_id, system_id):
        raise RuntimeError(KEY)

    monkeypatch.setattr(pipeline.firewall_unifi, "probe", boom)
    _scan(temp_db, monkeypatch)
    rows = temp_db.list_firewall_facts()
    assert len(rows) == 1 and rows[0]["stale"] == 1
    events = temp_db.list_device_error_events(system["id"])
    assert events and all(KEY not in e["message"] for e in events)


def test_switch_off_deletes_facts(temp_db, monkeypatch):
    _account(temp_db)
    monkeypatch.setattr(pipeline.firewall_unifi, "probe", _ok([]))
    _scan(temp_db, monkeypatch)
    assert temp_db.list_firewall_facts()
    _scan(temp_db, monkeypatch, firewall=False)
    assert temp_db.list_firewall_facts() == []


def test_allow_probe_revoked_deletes_facts(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    monkeypatch.setattr(pipeline.firewall_unifi, "probe", _ok([]))
    _scan(temp_db, monkeypatch)
    temp_db.update_account(account["id"], {"allowProbe": 0})
    _scan(temp_db, monkeypatch)
    assert temp_db.list_firewall_facts() == []


def test_source_failure_does_not_stop_others(temp_db, monkeypatch):
    first, _ = _account(temp_db)
    other, _ = _account(temp_db)
    seen: list = []

    async def probe(url, key, account_id, system_id):
        seen.append(account_id)
        if account_id == first["id"]:
            raise RuntimeError("x")
        return {"ok": True, "error": "", "facts": [FACT]}

    monkeypatch.setattr(pipeline.firewall_unifi, "probe", probe)
    _scan(temp_db, monkeypatch)
    assert set(seen) == {first["id"], other["id"]}
    assert [r["sourceAccountId"] for r in temp_db.list_firewall_facts()] == [other["id"]]
