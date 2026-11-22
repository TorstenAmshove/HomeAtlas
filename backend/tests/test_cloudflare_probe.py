import asyncio

import httpx

from app import cloudflare_probe, pipeline

ZONE, ACCT, TOKEN = "a" * 32, "b" * 32, "SECRET-CF-TOKEN"
RULESET = "c" * 32


def _routes(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        p = request.url.path
        if p.endswith("/dns_records"):
            return httpx.Response(200, json={"success": True, "result": [
                {"name": "App2.Example.net", "type": "CNAME", "content": f"{'d' * 8}.cfargotunnel.com", "proxied": True},
                {"name": "web.example.net", "type": "A", "content": "203.0.113.9", "proxied": False},
                {"name": "example.net", "type": "TXT", "content": "v=spf1 secret"}]})
        if p.endswith("/cfd_tunnel"):
            return httpx.Response(200, json={"success": True, "result": [
                {"id": "d" * 8, "name": "home", "status": "down", "token": "TUNNELSECRET"}]})
        if p.endswith(f"/rulesets/{RULESET}"):
            return httpx.Response(200, json={"success": True, "result": {"rules": [
                {"expression": '(http.host eq "app2.example.net" and not cf.tls_client_auth.cert_verified)'},
                {"expression": '(http.host eq "other.example.net")'}]}})
        if p.endswith("/rulesets"):
            return httpx.Response(200, json={"success": True, "result": [
                {"id": RULESET, "phase": "http_request_firewall_custom"}, {"id": "e" * 32, "phase": "other"}]})
        return httpx.Response(404)
    return handler


def _patch(monkeypatch, seen):
    transport = httpx.MockTransport(_routes(seen))

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            super().__init__(*a, **k)

    monkeypatch.setattr(cloudflare_probe.httpx, "AsyncClient", _Client)


def test_reads_only_with_get_and_keeps_allowlisted_fields(monkeypatch):
    seen = []
    _patch(monkeypatch, seen)
    result = asyncio.run(cloudflare_probe.probe(ZONE, ACCT, TOKEN))
    assert result["ok"] and {m for m, _ in seen} == {"GET"}
    assert not any(p.endswith("/token") for _, p in seen)
    kinds = {(f["kind"], f["key"]) for f in result["facts"]}
    assert ("cf_dns", "app2.example.net/CNAME") in kinds and ("cf_waf_mtls", "app2.example.net") in kinds
    assert ("cf_waf_mtls", "other.example.net") not in kinds
    assert not any(k == "cf_dns" and "TXT" in key for k, key in kinds)
    blob = str(result)
    assert "TUNNELSECRET" not in blob and TOKEN not in blob and "spf1" not in blob


def test_rejects_bad_ids_and_missing_token():
    assert "Zone-ID" in asyncio.run(cloudflare_probe.probe("../x", "", TOKEN))["error"]
    assert "Account-ID" in asyncio.run(cloudflare_probe.probe(ZONE, "zz", TOKEN))["error"]
    assert "Token" in asyncio.run(cloudflare_probe.probe(ZONE, "", ""))["error"]


def test_rejected_token_message_has_no_token(monkeypatch):
    transport = httpx.MockTransport(lambda r: httpx.Response(403))

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            super().__init__(*a, **k)

    monkeypatch.setattr(cloudflare_probe.httpx, "AsyncClient", _Client)
    result = asyncio.run(cloudflare_probe.probe(ZONE, "", TOKEN))
    assert not result["ok"] and TOKEN not in result["error"]


def _scan(temp_db, monkeypatch):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)

    async def no_rdns(ip):
        return {"hostname": "host.provider.example"}

    monkeypatch.setattr(pipeline.diagnostics, "reverse_dns", no_rdns)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("test")))


def test_pipeline_default_off_then_on_with_allow_probe(temp_db, monkeypatch):
    calls = []

    async def ok(zone, acct, token):
        calls.append(zone)
        return {"ok": True, "error": "", "facts": [
            {"kind": "cf_dns", "key": "w/A", "data": {"host": "w.example.net", "type": "A",
                                                       "target": "203.0.113.9", "proxied": False, "provider": ""}}]}

    monkeypatch.setattr(pipeline.cloudflare_probe, "probe", ok)
    temp_db.create_account({"label": "CF", "category": "cloudflare", "url": ZONE, "username": ACCT,
                            "allowProbe": 1})
    _scan(temp_db, monkeypatch)
    assert calls == [] and temp_db.list_exposure_facts() == []  # default off: no contact
    temp_db.update_settings({"scanEnableCloudflare": True})
    _scan(temp_db, monkeypatch)
    rows = temp_db.list_exposure_facts()
    assert len(calls) == 1 and rows[0]["source"] == "cloudflare"
    assert "host.provider.example" in str(rows[0]["data"])  # reverse-DNS label
