"""Regressions found against a real installation: Cloudflare page size, DDNSS hostname, Traefik TLS
without a resolver, and proxy targets on a Docker network."""
import asyncio

import httpx

from app import cloudflare_probe, db, docker_probe, docs, exposure

ZONE, TOKEN = "a" * 32, "SECRET-CF-TOKEN"
RULESET = "c" * 32


def _patch_cloudflare(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            super().__init__(*a, **k)

    monkeypatch.setattr(cloudflare_probe.httpx, "AsyncClient", _Client)


def test_waf_rules_are_read_within_the_rulesets_page_limit(monkeypatch):
    def handler(request):
        path = request.url.path
        if path.endswith("/dns_records"):
            return httpx.Response(200, json={"success": True, "result": []})
        if int(request.url.params.get("per_page", 0)) > 50:
            return httpx.Response(400, json={"success": False})
        if path.endswith(f"/rulesets/{RULESET}"):
            return httpx.Response(200, json={"success": True, "result": {"rules": [
                {"expression": '(http.host eq "app.example.net" and not cf.tls_client_auth.cert_verified)'}]}})
        return httpx.Response(200, json={"success": True, "result": [
            {"id": RULESET, "phase": "http_request_firewall_custom"}]})

    _patch_cloudflare(monkeypatch, handler)
    result = asyncio.run(cloudflare_probe.probe(ZONE, "", TOKEN))
    assert result["ok"] and result["warnings"] == []
    assert ("cf_waf_mtls", "app.example.net") in {(f["kind"], f["key"]) for f in result["facts"]}


def test_unreadable_waf_rules_are_reported_not_silently_dropped(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/dns_records"):
            return httpx.Response(200, json={"success": True, "result": []})
        return httpx.Response(403, text=TOKEN)

    _patch_cloudflare(monkeypatch, handler)
    result = asyncio.run(cloudflare_probe.probe(ZONE, "", TOKEN))
    assert result["ok"] and any("WAF" in w for w in result["warnings"])
    assert TOKEN not in str(result)


def test_ddnss_hostname_is_kept_and_its_key_is_not():
    env = ["DOMAIN_DDNSS=home.ddnss.example", "DOMAIN_KEY=SECRETKEY"]
    fact = docker_probe.ddns_fact("alcapone1933/ddns-ddnss:v0.0.8", env, "192.0.2.20")
    assert fact["data"]["hosts"] == ["home.ddnss.example"] and "SECRETKEY" not in str(fact)


def test_docker_probe_keeps_container_network_addresses(monkeypatch):
    container = {"Id": "a" * 64, "Names": ["/app"], "Image": "app:1", "State": "running", "Labels": {},
                 "NetworkSettings": {"Networks": {"proxy": {"IPAddress": "10.10.16.9"}, "none": {"IPAddress": ""}}}}

    async def fake_get(path):
        return [container] if path.startswith("/containers/json") else []

    monkeypatch.setattr(docker_probe, "socket_available", lambda: True)
    monkeypatch.setattr(docker_probe, "_get", fake_get)
    result = asyncio.run(docker_probe.probe("192.0.2.20"))
    assert result["systems"][0]["extra"]["docker"]["networkIps"] == ["10.10.16.9"]


def test_proxy_target_on_docker_network_resolves_to_the_container():
    systems = [{"id": "c", "name": "immich", "kind": "container", "ip": "192.0.2.20", "status": "online",
                "extra": {"docker": {"networkIps": ["10.10.16.9"]}}}]
    hit = exposure.resolve_target("http://10.10.16.9:2283", systems)
    assert hit["inInventory"] and hit["systems"][0]["id"] == "c"
    assert not exposure.resolve_target("http://10.10.16.10:2283", systems)["inInventory"]


def test_tls_router_without_resolver_is_shown_as_tls(temp_db):
    db.replace_exposure_facts("traefik", "t", [
        {"kind": "traefik_router", "key": "a", "data": {"hosts": ["a.example.net"], "service": "http://192.0.2.5:80",
                                                         "resolver": "", "middlewares": [], "tls": True}},
        {"kind": "traefik_router", "key": "b", "data": {"hosts": ["b.example.net"], "service": "http://192.0.2.6:80",
                                                         "resolver": "letsencrypt", "middlewares": [], "tls": True}}])
    body = docs._exposure_section()
    assert "TLS, Standardzertifikat" in body and "letsencrypt" in body
