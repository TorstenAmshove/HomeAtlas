import asyncio

import httpx

from app import pipeline, public_dns


def _patch(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            super().__init__(*a, **k)

    monkeypatch.setattr(public_dns.httpx, "AsyncClient", _Client)


def _answer(request):
    qtype = request.url.params["type"]
    if qtype == "A":
        return httpx.Response(200, json={"Answer": [
            {"type": 5, "data": "edge.example.net."}, {"type": 1, "data": "198.51.100.7"},
            {"type": 1, "data": "not-an-ip"}]})
    return httpx.Response(200, json={})


def test_hostnames_skip_wildcards_invalid_and_internal_routes():
    facts = [
        {"kind": "caddy_site", "data": {"host": "App1.example.net"}},
        {"kind": "caddy_site", "data": {"host": "*.example.net"}},
        {"kind": "tunnel_ingress", "data": {"host": "bad host!"}},
        {"kind": "traefik_router", "data": {"hosts": ["x.lan.example.org"]}},
        {"kind": "ddns", "data": {"hosts": ["dyn.example.net"]}},
    ]
    assert public_dns.hostnames(facts) == ["app1.example.net", "dyn.example.net"]


def test_resolves_with_get_to_fixed_resolver_and_keeps_only_ips(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url).split("?")[0]))
        return _answer(request)

    _patch(monkeypatch, handler)
    result = asyncio.run(public_dns.resolve(["app1.example.net", "*.example.net"]))
    assert result["ok"] and {m for m, _ in seen} == {"GET"} and {u for _, u in seen} == {public_dns.RESOLVER}
    assert len(seen) == 2  # A + AAAA, the wildcard was never asked
    assert result["facts"][0]["data"] == {"host": "app1.example.net", "addrs": ["198.51.100.7"],
                                          "cname": "edge.example.net"}


def test_query_limit_reports_skipped(monkeypatch):
    seen = []
    _patch(monkeypatch, lambda r: (seen.append(1), _answer(r))[1])
    hosts = [f"h{i}.example.net" for i in range(150)]
    result = asyncio.run(public_dns.resolve(hosts))
    assert len(seen) == public_dns.MAX_QUERIES and result["skipped"] == 50


def test_oversized_answer_and_all_failures(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(200, content=b"x" * 70000))
    result = asyncio.run(public_dns.resolve(["a.example.net"]))
    assert not result["ok"]


def test_pipeline_default_off_makes_no_call(temp_db, monkeypatch):
    calls = []

    async def fake(hosts):
        calls.append(hosts)
        return {"ok": True, "error": "", "skipped": 0, "facts": [{"kind": "dns", "key": "a.example.net",
                "data": {"host": "a.example.net", "addrs": ["198.51.100.7"], "cname": ""}}]}

    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline.public_dns, "resolve", fake)

    async def fake_docker(host_ip=""):  # the runner may have a real socket; stay deterministic
        return {"ok": True, "error": "", "systems": [], "ddns": [
            {"kind": "ddns", "key": "a", "data": {"hosts": ["a.example.net"]}}]}

    monkeypatch.setattr(pipeline.docker_probe, "probe", fake_docker)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("t")))
    assert calls == []
    temp_db.update_settings({"scanEnablePublicDns": True})
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("t")))
    assert calls == [["a.example.net"]]
    assert any(r["source"] == "public_dns" for r in temp_db.list_exposure_facts())
