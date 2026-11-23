"""The UniFi adapter only consumes documented local GET endpoints and emits HomeAtlas findings."""
import asyncio

import httpx

from app import unifi_probe


def _page(data):
    return {"count": len(data), "data": data, "limit": 200, "offset": 0, "totalCount": len(data)}


def test_probe_normalizes_all_unifi_sites_without_persisting_api_key(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/v1/info"):
            return httpx.Response(200, json={"applicationVersion": "10.4.57"})
        if path.endswith("/v1/sites"):
            return httpx.Response(200, json=_page([{"id": "site-1", "name": "Zuhause", "internalReference": "default"}]))
        if path.endswith("/v1/sites/site-1/devices"):
            return httpx.Response(200, json=_page([
                {"id": "gateway", "name": "UCG Ultra", "ipAddress": "192.168.1.1", "macAddress": "AA-BB-CC-DD-EE-01",
                 "model": "UCG-Ultra", "state": "ONLINE", "features": ["gateway"], "interfaces": [], "supported": True,
                 "firmwareVersion": "4.1.13", "firmwareUpdatable": False},
                {"id": "switch", "name": "Wohnzimmer-Switch", "ipAddress": "192.168.1.2", "macAddress": "AA-BB-CC-DD-EE-02",
                 "model": "USW-Lite-8-PoE", "state": "ONLINE", "features": ["switching"], "interfaces": ["ports"], "supported": True,
                 "firmwareVersion": "7.1.26", "firmwareUpdatable": False},
                {"id": "ap", "name": "Wohnzimmer AP", "ipAddress": "192.168.1.3", "macAddress": "AA-BB-CC-DD-EE-03",
                 "model": "U6-Lite", "state": "OFFLINE", "features": ["accessPoint"], "interfaces": ["radios"], "supported": True,
                 "firmwareVersion": "6.6.77", "firmwareUpdatable": True},
            ]))
        if path.endswith("/v1/sites/site-1/devices/gateway"):
            return httpx.Response(200, json={"id": "gateway", "interfaces": {}, "features": {}, "firmwareUpdatable": False,
                                               "ipAddress": "192.168.1.1", "macAddress": "AA:BB:CC:DD:EE:01", "model": "UCG-Ultra",
                                               "name": "UCG Ultra", "state": "ONLINE", "supported": True})
        if path.endswith("/v1/sites/site-1/devices/switch"):
            return httpx.Response(200, json={"id": "switch", "interfaces": {}, "features": {}, "firmwareUpdatable": False,
                                               "ipAddress": "192.168.1.2", "macAddress": "AA:BB:CC:DD:EE:02", "model": "USW-Lite-8-PoE",
                                               "name": "Wohnzimmer-Switch", "state": "ONLINE", "supported": True,
                                               "uplink": {"deviceId": "gateway"}})
        if path.endswith("/v1/sites/site-1/devices/ap"):
            return httpx.Response(200, json={"id": "ap", "interfaces": {}, "features": {}, "firmwareUpdatable": True,
                                               "ipAddress": "192.168.1.3", "macAddress": "AA:BB:CC:DD:EE:03", "model": "U6-Lite",
                                               "name": "Wohnzimmer AP", "state": "OFFLINE", "supported": True,
                                               "uplink": {"deviceId": "switch"}})
        if path.endswith("/v1/sites/site-1/clients"):
            return httpx.Response(200, json=_page([
                {"id": "client", "name": "Drucker", "type": "WIRED", "ipAddress": "192.168.1.50", "macAddress": "AA:BB:CC:DD:EE:50",
                 "uplinkDeviceId": "switch", "access": {"type": "DEFAULT"}},
                {"id": "teleport", "name": "Fernzugang", "type": "TELEPORT", "ipAddress": "10.0.0.1", "access": {"type": "DEFAULT"}},
            ]))
        if path.endswith("/v1/sites/site-1/networks"):
            return httpx.Response(200, json=_page([
                {"id": "iot", "name": "IoT", "management": "GATEWAY", "vlanId": 20, "enabled": True, "default": False,
                 "metadata": {"origin": "USER_DEFINED"}},
            ]))
        if path.endswith("/v1/sites/site-1/networks/iot"):
            return httpx.Response(200, json={"id": "iot", "name": "IoT", "management": "GATEWAY", "vlanId": 20, "enabled": True,
                                               "default": False, "metadata": {"origin": "USER_DEFINED"}, "internetAccessEnabled": True,
                                               "isolationEnabled": True, "ipv4Configuration": {"hostIpAddress": "192.168.20.1", "prefixLength": 24,
                                               "autoScaleEnabled": False, "dhcpConfiguration": {"mode": "SERVER", "ipAddressRange": {"start": "192.168.20.6", "stop": "192.168.20.254"}}}})
        if path.endswith("/v1/sites/site-1/wifi/broadcasts"):
            return httpx.Response(200, json=_page([
                {"id": "wifi-iot", "name": "IoT WLAN", "type": "STANDARD", "enabled": True, "metadata": {"origin": "USER_DEFINED"},
                 "network": {"type": "SPECIFIC", "networkId": "iot"}, "securityConfiguration": {"type": "WPA2_WPA3_PERSONAL"}},
            ]))
        if path.endswith("/v1/sites/site-1/wans"):
            return httpx.Response(200, json=_page([{"id": "wan-1", "name": "Internet 1"}]))
        raise AssertionError(f"unexpected request: {request.url}")

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(unifi_probe.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))

    result = asyncio.run(unifi_probe.probe("https://192.168.1.1", "api-secret", "account-1", "ucg-system"))

    assert result["ok"]
    assert result["warnings"] == []
    assert {system["name"] for system in result["systems"]} == {
        "UCG Ultra", "Wohnzimmer-Switch", "Wohnzimmer AP", "Drucker",
    }
    ap = next(system for system in result["systems"] if system["name"] == "Wohnzimmer AP")
    assert ap["kind"] == "network"
    assert ap["status"] == "offline"
    assert ap["extra"]["unifi"]["uplinkDeviceId"] == "switch"
    assert ap["extra"]["unifi"]["name"] == "Wohnzimmer AP"
    assert next(system for system in result["systems"] if system["name"] == "UCG Ultra")["kind"] == "router"
    network = next(resource for resource in result["resources"] if resource["kind"] == "network")
    assert network["facts"]["cidr"] == "192.168.20.0/24"
    assert network["facts"]["dhcpRange"] == "192.168.20.6 - 192.168.20.254"
    wifi = next(resource for resource in result["resources"] if resource["kind"] == "wifi")
    assert wifi["facts"] == {"networkExternalId": "iot", "networkName": "IoT", "security": "WPA2_WPA3_PERSONAL", "type": "STANDARD"}
    assert "api-secret" not in str(result)
    assert all(request.headers["X-API-Key"] == "api-secret" for request in requests)
    assert all(request.method == "GET" for request in requests)
    assert result["completeScopes"] == [("site-1", "network"), ("site-1", "wifi"), ("site-1", "wan")]


def test_probe_reports_authentication_failure_without_echoing_api_key(monkeypatch):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "Unauthorized"}))
    monkeypatch.setattr(unifi_probe.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))

    result = asyncio.run(unifi_probe.probe("https://192.168.1.1", "api-secret", "account-1", None))

    assert not result["ok"]
    assert "API-Key" in result["error"]
    assert "api-secret" not in result["error"]
    assert result["systems"] == []


def _mock_clients(monkeypatch, clients):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v1/info"):
            return httpx.Response(200, json={})
        if path.endswith("/v1/sites"):
            return httpx.Response(200, json=_page([{"id": "s", "name": "Z"}]))
        if path.endswith("/devices"):
            return httpx.Response(200, json=_page([
                {"id": "ap", "name": "AP", "ipAddress": "10.99.0.2", "macAddress": "AA-BB-CC-DD-EE-03",
                 "model": "U6", "state": "ONLINE", "features": ["accessPoint"]}]))
        if "/devices/" in path:
            return httpx.Response(200, json={})
        if path.endswith("/clients"):
            return httpx.Response(200, json=_page(clients))
        return httpx.Response(200, json=_page([]))

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(unifi_probe.httpx, "AsyncClient", lambda **kw: client_type(transport=transport, **kw))


def _c(i, ip, type_="WIRED"):
    c = {"id": f"c{i}", "name": f"c{i}", "type": type_, "macAddress": f"AA:BB:CC:DD:00:{i:02d}"}
    if ip is not None:
        c["ipAddress"] = ip
    return c


_CLIENTS = [_c(1, "192.168.1.0"), _c(2, "192.168.1.255"), _c(3, "192.168.50.7"), _c(4, None),
            _c(5, "fe80::1"), _c(6, "192.168.1.9", "TELEPORT")]


def test_probe_filters_clients_by_subnets(monkeypatch):
    _mock_clients(monkeypatch, _CLIENTS)
    result = asyncio.run(unifi_probe.probe("https://x", "k", "a", None, client_subnets=["192.168.1.0/24"]))
    assert {s["name"] for s in result["systems"]} == {"AP", "c1", "c2"}
    assert result["skippedClients"] == 3


def test_probe_without_client_subnets_keeps_all_clients(monkeypatch):
    _mock_clients(monkeypatch, _CLIENTS)
    for value in (None, []):
        result = asyncio.run(unifi_probe.probe("https://x", "k", "a", None, client_subnets=value))
        assert {s["name"] for s in result["systems"]} == {"AP", "c1", "c2", "c3", "c4", "c5"}
        assert result["skippedClients"] == 0


def test_probe_ignores_invalid_subnet_entries(monkeypatch):
    _mock_clients(monkeypatch, [_c(1, "10.0.0.7"), _c(2, "192.168.50.7")])
    result = asyncio.run(unifi_probe.probe("https://x", "k", "a", None, client_subnets=["müll", "10.0.0.5/24"]))
    assert {s["name"] for s in result["systems"]} == {"AP", "c1"}
    result = asyncio.run(unifi_probe.probe("https://x", "k", "a", None, client_subnets=["müll"]))
    assert {s["name"] for s in result["systems"]} == {"AP", "c1", "c2"}
