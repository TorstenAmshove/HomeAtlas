import asyncio

from app import pipeline

KEY = "key-secret-12345"
FACT = {"kind": "zone", "key": "zone:default:z1", "data": {"id": "z1", "name": "DMZ"}}


def _scan(db, monkeypatch, firewall=True):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline.crypto, "decrypt_strict", lambda value: KEY)
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


# ---- nftables --------------------------------------------------------------------------------

NFT_FACTS = [{"kind": "nft_host", "key": "nft:s", "data": {"systemId": "s", "chains": 0, "rules": 0}}]


def _nft_account(db, ip="192.0.2.5", label="Host"):
    system = db.create_system({"name": label, "ip": ip, "kind": "server"})
    account = db.create_account({"label": label, "category": "firewall_nftables", "systemId": system["id"],
                                 "allowProbe": 1})
    return account, system


def _nft_scan(db, monkeypatch, probe, on=True, unifi=False):
    monkeypatch.setattr(pipeline.firewall_nft, "probe", probe)
    db.update_settings({"scanEnableFirewallNft": on})  # _scan only touches the UniFi switch
    _scan(db, monkeypatch, firewall=unifi)


async def _nft_ok(host, acct):
    return {"ok": True, "error": "", "facts": NFT_FACTS}


async def _nft_boom(host, acct):
    raise RuntimeError(KEY)


def test_nft_default_is_off(temp_db):
    assert temp_db.get_settings()["scanEnableFirewallNft"] is False


def test_nft_success_replaces_facts(temp_db, monkeypatch):
    account, _ = _nft_account(temp_db)
    _nft_scan(temp_db, monkeypatch, _nft_ok)
    rows = temp_db.list_firewall_facts()
    assert [(r["source"], r["sourceAccountId"], r["stale"]) for r in rows] == [("nftables", account["id"], 0)]


def test_nft_failure_marks_stale(temp_db, monkeypatch):
    _, system = _nft_account(temp_db)
    _nft_scan(temp_db, monkeypatch, _nft_ok)
    _nft_scan(temp_db, monkeypatch, _nft_boom)
    rows = temp_db.list_firewall_facts()
    assert len(rows) == 1 and rows[0]["stale"] == 1
    assert all(KEY not in e["message"] for e in temp_db.list_device_error_events(system["id"]))


def test_nft_switch_off_deletes_facts(temp_db, monkeypatch):
    _nft_account(temp_db)
    _nft_scan(temp_db, monkeypatch, _nft_ok)
    assert temp_db.list_firewall_facts()
    _nft_scan(temp_db, monkeypatch, _nft_ok, on=False)
    assert temp_db.list_firewall_facts() == []


def test_nft_allow_probe_revoked_deletes_facts(temp_db, monkeypatch):
    account, _ = _nft_account(temp_db)
    _nft_scan(temp_db, monkeypatch, _nft_ok)
    temp_db.update_account(account["id"], {"allowProbe": 0})
    _nft_scan(temp_db, monkeypatch, _nft_ok)
    assert temp_db.list_firewall_facts() == []


def test_one_nft_host_failure_does_not_stop_others(temp_db, monkeypatch):
    _nft_account(temp_db, "192.0.2.5", "Bad")
    good, _ = _nft_account(temp_db, "192.0.2.6", "Good")

    async def probe(host, acct):
        if host == "192.0.2.5":
            raise RuntimeError("x")
        return {"ok": True, "error": "", "facts": NFT_FACTS}

    _nft_scan(temp_db, monkeypatch, probe)
    assert {r["sourceAccountId"] for r in temp_db.list_firewall_facts()} == {good["id"]}


def test_nft_source_failure_does_not_stop_unifi(temp_db, monkeypatch):
    _account(temp_db)
    _nft_account(temp_db)
    monkeypatch.setattr(pipeline.firewall_unifi, "probe", _ok([]))
    _nft_scan(temp_db, monkeypatch, _nft_boom, unifi=True)
    assert {r["source"] for r in temp_db.list_firewall_facts()} == {"unifi"}
