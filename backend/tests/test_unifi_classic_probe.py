import asyncio

import httpx
import pytest

from app import unifi_classic_probe as probe_mod

KEY = "key-secret-12345"
_REAL_CLIENT = httpx.AsyncClient


def _run(handler, monkeypatch, key=KEY, url="https://gw"):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", lambda **k: _REAL_CLIENT(transport=transport, **k))
    return asyncio.run(probe_mod.probe(url, key, "acc", "sys"))


def _handler(requests, forwards, health, sites=None, stations=None):
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
        if path.endswith("/stat/sta"):
            return httpx.Response(200, json={"data": stations or []})
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


WIRED = {"mac": "AA-BB-CC-00-00-01", "is_wired": True, "sw_mac": "AA:BB:CC:00:00:10", "sw_port": 5}
WIFI = {"mac": "aa:bb:cc:00:00:02", "is_wired": False, "ap_mac": "aa:bb:cc:00:00:20", "essid": "Zuhause"}


def test_clients_read_wired_and_wifi(monkeypatch):
    result = _run(_handler([], [], [], stations=[WIRED, WIFI]), monkeypatch)
    assert result["clients"] == [
        {"site": "default", "mac": "aa:bb:cc:00:00:01", "wired": True, "swMac": "aa:bb:cc:00:00:10",
         "swPort": 5, "apMac": "", "essid": ""},
        {"site": "default", "mac": "aa:bb:cc:00:00:02", "wired": False, "swMac": "", "swPort": None,
         "apMac": "aa:bb:cc:00:00:20", "essid": "Zuhause"}]


def test_clients_keep_only_allowlisted_fields(monkeypatch):
    extra = {**WIRED, "name": "Geheim-TV", "hostname": "tv", "ip": "192.0.2.9", "x_passphrase": "PW",
             "network_id": "net1", "network": "LAN"}
    result = _run(_handler([], [], [], stations=[extra]), monkeypatch)
    assert set(result["clients"][0]) == {"site", "mac", "wired", "swMac", "swPort", "apMac", "essid"}
    text = str(result)
    assert not any(x in text for x in ("Geheim-TV", "192.0.2.9", "PW", "net1"))


def test_client_without_mac_dropped_and_missing_fields_tolerated(monkeypatch):
    stations = [{"is_wired": True, "sw_port": 1}, {"mac": "aa:bb:cc:00:00:03"},
                {"mac": "aa:bb:cc:00:00:04", "ap_mac": "aa:bb:cc:00:00:20"},
                {"mac": "aa:bb:cc:00:00:05", "is_wired": True, "sw_port": 1000},
                {"mac": "aa:bb:cc:00:00:06", "is_wired": True, "sw_port": True}]
    result = _run(_handler([], [], [], stations=stations), monkeypatch)
    by_mac = {c["mac"]: c for c in result["clients"]}
    assert set(by_mac) == {"aa:bb:cc:00:00:04", "aa:bb:cc:00:00:05", "aa:bb:cc:00:00:06"}
    assert by_mac["aa:bb:cc:00:00:04"]["wired"] is False
    assert by_mac["aa:bb:cc:00:00:05"]["swPort"] is None and by_mac["aa:bb:cc:00:00:06"]["swPort"] is None


@pytest.mark.parametrize("response", [
    httpx.Response(404, text=KEY), httpx.Response(403, text=KEY), httpx.Response(429, text=KEY),
    httpx.Response(500, text=KEY), httpx.Response(200, text="no json"),
    httpx.Response(200, json={"data": {"a": 1}})])
def test_stat_sta_errors_keep_forwards(monkeypatch, response):
    fw = [{"proto": "tcp", "dst_port": "1", "fwd": "192.0.2.1", "fwd_port": "1"}]

    def handler(request):
        if request.url.path.endswith("/stat/sta"):
            return response
        return _handler([], fw, [])(request)

    result = _run(handler, monkeypatch)
    assert result["ok"] and result["clients"] == [] and len(result["forwards"]) == 2
    assert any("Client-Zuordnung" in w for w in result["warnings"]) and KEY not in str(result)


def test_clients_capped_with_single_warning(monkeypatch):
    stations = [{"mac": f"aa:bb:cc:{i // 256:02x}:{i % 256:02x}:01", "is_wired": True, "sw_port": 1}
                for i in range(probe_mod._MAX_CLIENTS + 5)]
    result = _run(_handler([], [], [], stations=stations), monkeypatch)
    assert len(result["clients"]) == probe_mod._MAX_CLIENTS
    assert sum("Clients" in w for w in result["warnings"]) == 1


def test_same_mac_in_two_sites_stays_separate(monkeypatch):
    result = _run(_handler([], [], [], sites=[{"name": "default"}, {"name": "b2"}], stations=[WIRED]), monkeypatch)
    assert [c["site"] for c in result["clients"]] == ["default", "b2"]
