import asyncio

import httpx

from app import pipeline, traefik_probe

HASH = "admin:$apr1$SECRETHASH$abcdef"

ROUTERS = [
    {"name": "app@docker", "rule": "Host(`app.lan.example.org`) || Host(`alt.lan.example.org`)",
     "service": "app-svc@docker", "entryPoints": ["websecure"], "middlewares": ["auth@file"],
     "tls": {"certResolver": "dnschallenge"}, "users": HASH},
    {"name": "regex", "rule": "HostRegexp(`^.+\\.lan\\.example\\.org$`)", "service": "app-svc@docker",
     "entryPoints": ["web"]},
    {"name": "api", "rule": "PathPrefix(`/api`)", "service": "api@internal", "entryPoints": ["traefik"]},
]
SERVICES = [
    {"name": "app-svc@docker", "loadBalancer": {"servers": [{"url": "http://192.0.2.20:8080"}]}},
    {"name": "api@internal"},
]
ENTRYPOINTS = [{"name": "websecure", "address": ":443"}, {"name": "web", "address": ":80"}]


def _fake_client(monkeypatch, routes, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.method, request.url.path))
        return routes.get(request.url.path, httpx.Response(404))

    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(traefik_probe.httpx, "AsyncClient", _Client)


def _routes():
    return {"/api/http/routers": httpx.Response(200, json=ROUTERS),
            "/api/http/services": httpx.Response(200, json=SERVICES),
            "/api/entrypoints": httpx.Response(200, json=ENTRYPOINTS)}


def test_requires_address_and_credentials():
    assert "Adresse" in asyncio.run(traefik_probe.probe("", "u", "p"))["error"]
    assert "fehlt" in asyncio.run(traefik_probe.probe("http://t.lan", "", ""))["error"]


def test_reads_routers_only_with_get_and_fixed_paths(monkeypatch):
    seen: list = []
    _fake_client(monkeypatch, _routes(), seen)
    result = asyncio.run(traefik_probe.probe("http://t.lan", "u", "p"))
    assert result["ok"]
    assert {m for m, _ in seen} == {"GET"}
    assert {p for _, p in seen} == {"/api/http/routers", "/api/http/services", "/api/entrypoints"}
    by_key = {f["key"]: f["data"] for f in result["facts"]}
    assert set(by_key) == {"app@docker", "regex", "api"}  # every route listed
    app = by_key["app@docker"]
    assert app["hosts"] == ["app.lan.example.org", "alt.lan.example.org"]
    assert app["service"] == "http://192.0.2.20:8080"
    assert app["resolver"] == "dnschallenge" and app["tls"] is True
    assert app["middlewares"] == ["auth@file"]
    assert by_key["regex"]["hosts"] == [] and by_key["regex"]["tls"] is False
    assert by_key["api"]["service"] == ""  # @internal has no target
    assert all(f["kind"] == "traefik_router" for f in result["facts"])


def test_no_secret_in_result_or_error(monkeypatch):
    _fake_client(monkeypatch, _routes())
    result = asyncio.run(traefik_probe.probe("http://t.lan", "u", "p"))
    assert "SECRETHASH" not in str(result)


def test_no_secret_in_error_text(monkeypatch):
    _fake_client(monkeypatch, {"/api/http/routers": httpx.Response(500, text=HASH)})
    failed = asyncio.run(traefik_probe.probe("http://u:hunter2@t.lan", "u", "hunter2"))
    assert not failed["ok"] and "SECRETHASH" not in str(failed) and "hunter2" not in str(failed)


def test_rejected_credentials(monkeypatch):
    _fake_client(monkeypatch, {"/api/http/routers": httpx.Response(401)})
    result = asyncio.run(traefik_probe.probe("http://t.lan", "u", "bad"))
    assert not result["ok"] and "abgelehnt" in result["error"]


def test_pagination(monkeypatch):
    pages = {"1": httpx.Response(200, json=ROUTERS[:1], headers={"X-Next-Page": "2"}),
             "2": httpx.Response(200, json=ROUTERS[1:2], headers={"X-Next-Page": "2"})}

    def handler(request):
        if request.url.path == "/api/http/routers":
            return pages[request.url.params.get("page", "1")]
        return _routes().get(request.url.path, httpx.Response(404))

    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            k.pop("verify", None)
            super().__init__(*a, **k)

    monkeypatch.setattr(traefik_probe.httpx, "AsyncClient", _Client)
    result = asyncio.run(traefik_probe.probe("http://t.lan", "u", "p"))
    assert [f["key"] for f in result["facts"]] == ["app@docker", "regex"]


def _account(temp_db):
    system = temp_db.create_system({"kind": "server", "name": "Proxy", "ip": "192.0.2.5"})
    return temp_db.create_account({"systemId": system["id"], "label": "Traefik", "category": "traefik",
                                   "url": "http://t.lan", "username": "u", "allowProbe": 1}), system


def _scan(temp_db, monkeypatch):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("test")))


def test_pipeline_stores_facts_then_marks_stale_on_failure(temp_db, monkeypatch):
    account, system = _account(temp_db)

    async def ok(url, user, pw):
        return {"ok": True, "error": "", "facts": [{"kind": "traefik_router", "key": "r",
                                                    "data": {"hosts": ["a.lan"], "service": "http://192.0.2.20:80"}}]}

    monkeypatch.setattr(pipeline.traefik_probe, "probe", ok)
    _scan(temp_db, monkeypatch)
    rows = temp_db.list_exposure_facts()
    assert [r["source"] for r in rows] == ["traefik"] and rows[0]["stale"] == 0

    async def boom(url, user, pw):
        return {"ok": False, "error": "Traefik nicht erreichbar", "facts": []}

    monkeypatch.setattr(pipeline.traefik_probe, "probe", boom)
    _scan(temp_db, monkeypatch)
    assert temp_db.list_exposure_facts()[0]["stale"] == 1
    assert any("nicht erreichbar" in e["message"] for e in temp_db.list_device_error_events(system["id"]))


def test_pipeline_skips_without_allow_probe_or_switch(temp_db, monkeypatch):
    account, _ = _account(temp_db)
    calls = []

    async def ok(url, user, pw):
        calls.append(url)
        return {"ok": True, "error": "", "facts": [{"kind": "traefik_router", "key": "r", "data": {}}]}

    monkeypatch.setattr(pipeline.traefik_probe, "probe", ok)
    _scan(temp_db, monkeypatch)
    assert len(calls) == 1 and temp_db.list_exposure_facts()
    temp_db.update_account(account["id"], {"allowProbe": 0})
    _scan(temp_db, monkeypatch)
    assert len(calls) == 1 and temp_db.list_exposure_facts() == []  # facts removed with the opt-in


def test_pipeline_switch_off_makes_no_call(temp_db, monkeypatch):
    _account(temp_db)
    calls = []

    async def ok(url, user, pw):
        calls.append(url)
        return {"ok": True, "error": "", "facts": []}

    monkeypatch.setattr(pipeline.traefik_probe, "probe", ok)
    temp_db.update_settings({"scanEnableTraefik": False})
    _scan(temp_db, monkeypatch)
    assert calls == []
