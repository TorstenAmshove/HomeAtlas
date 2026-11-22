import asyncio

import httpx

from app import unifi_classic_probe as probe_mod

KEY = "key-secret-12345"
_REAL_CLIENT = httpx.AsyncClient


def _run(handler, monkeypatch, key=KEY, url="https://gw"):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", lambda **k: _REAL_CLIENT(transport=transport, **k))
    return asyncio.run(probe_mod.probe(url, key, "acc", "sys"))


def _handler(requests, forwards, health, sites=None):
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/self/sites"):
            return httpx.Response(200, json={"data": sites or [{"name": "default"}, {"name": "../x"}]})
        if path.endswith("/rest/portforward"):
            return httpx.Response(200, json={"data": forwards})
        if path.endswith("/rest/networkconf"):
            return httpx.Response(200, json={"data": [
                {"name": "DSL", "purpose": "wan", "wan_networkgroup": "WAN", "wan_type": "dhcp",
                 "x_password": "PPPOESECRET"},
                {"name": "Reserve", "purpose": "wan", "wan_networkgroup": "WAN2", "wan_type": "dhcp"},
                {"name": "LAN", "purpose": "corporate"}]})
        if path.endswith("/stat/device"):
            return httpx.Response(200, json={"data": health})
        raise AssertionError(path)
    return handler


def test_probe_uses_api_key_only(monkeypatch):
    requests: list = []
    fw = [{"name": "Geheim", "enabled": True, "proto": "tcp", "dst_port": "443", "fwd": "192.0.2.20",
           "fwd_port": "8443", "destination_ips": ["1.2.3.4"], "_id": "x"},
          {"enabled": False, "proto": "tcp_udp", "dst_port": "1-5", "fwd": "nonsense", "fwd_port": "1"}]
    gateway = {"type": "udm", "uplink": {"comment": "WAN"}, "x_passphrase": "no",
               "last_wan_interfaces": {"WAN": {"ip": "192.168.178.20", "alive": True}},
               "last_wan_status": {"WAN": "online"}, "geo_info": {"WAN": {"address": "8.8.4.4"}}}
    result = _run(_handler(requests, fw, [{"type": "usw"}, gateway]), monkeypatch)
    assert result["ok"]
    forwards = [f for f in result["forwards"] if f["kind"] == "portforward"]
    assert [f["data"] for f in forwards] == [
        {"proto": "TCP", "wanPort": "443", "destIp": "192.0.2.20", "destPort": "8443", "enabled": True}]
    assert result["forwards"][-1] == {"kind": "portforward_scan", "key": "scan", "data": {"count": 1}}
    assert result["wans"][0] == {"name": "DSL", "group": "WAN", "type": "dhcp", "active": True, "ip": "8.8.4.4",
                                 "interfaceIp": "192.168.178.20", "publicIp": "8.8.4.4", "publicOrigin": "geo"}
    assert result["wans"][1]["name"] == "Reserve" and not result["wans"][1]["active"] and not result["wans"][1]["ip"]
    assert result["wanFacts"] == [{"kind": "wan_address", "key": "unifi:default:WAN",
                                   "data": {"ip": "8.8.4.4", "source": "UniFi", "origin": "geo"}}]
    assert "PPPOESECRET" not in str(result)
    assert {r.method for r in requests} == {"GET"}
    assert all(r.headers["X-API-Key"] == KEY for r in requests)
    assert all(not {"cookie", "x-csrf-token", "authorization"} & set(r.headers) for r in requests)
    assert all("/api/auth/login" not in r.url.path for r in requests)
    assert "Geheim" not in str(result) and "1.2.3.4" not in str(result) and KEY not in str(result)


def test_no_forwards_is_a_successful_empty_scan(monkeypatch):
    result = _run(_handler([], [], []), monkeypatch)
    assert result["ok"] and result["forwards"] == [{"kind": "portforward_scan", "key": "scan", "data": {"count": 0}}]


def test_probe_errors_have_no_key(monkeypatch):
    for status, text in ((401, "abgelehnt"), (403, "abgelehnt"), (404, "nicht verfügbar"), (400, "nicht verfügbar"),
                         (302, "Weiterleitung"), (500, "Status 500")):
        result = _run(lambda r, s=status: httpx.Response(s, text=KEY), monkeypatch)
        assert not result["ok"] and text in result["error"] and KEY not in result["error"], status


def test_bad_bodies_and_timeout_are_fixed_messages(monkeypatch):
    for response in (httpx.Response(200, text=KEY), httpx.Response(200, json={"data": "x"}),
                     httpx.Response(200, json={"meta": {"rc": "error"}, "data": []})):
        result = _run(lambda r, resp=response: resp, monkeypatch)
        assert not result["ok"] and KEY not in result["error"]

    def timeout(request):
        raise httpx.ReadTimeout(KEY)

    result = _run(timeout, monkeypatch)
    assert not result["ok"] and KEY not in result["error"]


def test_partial_failure_discards_what_was_read(monkeypatch):
    def handler(request):
        if request.url.path == "/proxy/network/api/s/b2/rest/portforward":
            return httpx.Response(403)
        return _handler([], [{"proto": "tcp", "dst_port": "1", "fwd": "192.0.2.1", "fwd_port": "1"}], [],
                        sites=[{"name": "default"}, {"name": "b2"}])(request)

    result = _run(handler, monkeypatch)
    assert not result["ok"] and result["forwards"] == []


def test_unreadable_wan_status_keeps_forwards_and_warns(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/rest/networkconf"):
            return httpx.Response(403, text=KEY)
        return _handler([], [{"proto": "tcp", "dst_port": "1", "fwd": "192.0.2.1", "fwd_port": "1"}], [])(request)

    result = _run(handler, monkeypatch)
    assert result["ok"] and result["wans"] == [] and len(result["forwards"]) == 2
    assert any("WAN-Status" in w for w in result["warnings"]) and KEY not in str(result)


def test_multiple_sites(monkeypatch):
    requests: list = []
    _run(_handler(requests, [], [], sites=[{"name": "default"}, {"name": "b2"}, {"name": "bad name"}]), monkeypatch)
    assert [r.url.path for r in requests if r.url.path.endswith("/rest/portforward")] == [
        "/proxy/network/api/s/default/rest/portforward", "/proxy/network/api/s/b2/rest/portforward"]


def test_missing_or_invalid_input_makes_no_request(monkeypatch):
    def boom(request):
        raise AssertionError("no request")

    assert not _run(boom, monkeypatch, key="")["ok"]
    assert not _run(boom, monkeypatch, url="")["ok"]
    for bad in ("key with space", "key\nnewline-123", "short"):
        assert "Ungültig" in _run(boom, monkeypatch, key=bad)["error"]
