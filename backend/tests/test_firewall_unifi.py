import asyncio

import httpx

from app import firewall_unifi as fw

KEY = "key-secret-12345"
_REAL_CLIENT = httpx.AsyncClient
ZONE_A, ZONE_B = "22e1ab1c-0000-4000-8000-000000000001", "64076345-0000-4000-8000-000000000002"


def _run(handler, monkeypatch, key=KEY, url="https://gw"):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(fw.httpx, "AsyncClient", lambda **k: _REAL_CLIENT(transport=transport, **k))
    return asyncio.run(fw.probe(url, key, "acc", "sys"))


def _side(zone, **extra):
    return {"match_opposite_ports": False, "matching_target": "ANY", "port_matching_type": "ANY",
            "zone_id": zone, **extra}


def _policy(pid, index, **extra):
    base = {"_id": pid, "action": "ALLOW", "connection_state_type": "ALL", "enabled": True, "index": index,
            "ip_version": "BOTH", "name": f"Regel {pid}", "predefined": False, "protocol": "tcp",
            "schedule": {"mode": "ALWAYS"}, "source": _side(ZONE_A), "destination": _side(ZONE_B),
            "hits": 5, "description": "geheimer Kommentar"}
    base.update(extra)
    return base


ZONES = [{"_id": ZONE_A, "external_id": "x1", "name": "DMZ", "zone_key": "dmz", "default_zone": False,
          "network_ids": ["net-1", "net-2"], "attr_no_edit": False},
         {"_id": ZONE_B, "external_id": "x2", "name": "Server", "zone_key": "", "default_zone": False,
          "network_ids": []}]
GROUPS = [{"_id": "g1", "name": "Sonos", "group_type": "address-group", "group_members": ["192.168.21.120-192.168.21.129"]},
          {"_id": "g2", "name": "SSH", "group_type": "port-group", "group_members": ["22"]},
          {"_id": "g3", "name": "Netz", "group_type": "address-group", "group_members": ["10.0.0.0/8"]}]


NETWORKS = [{"_id": "net-1", "ip_subnet": "192.0.2.2/26", "name": "DMZ", "x_password": "wan-geheim"},
            {"_id": "net-2", "ip_subnet": "192.0.2.66/26"},
            {"_id": "net-wan", "purpose": "wan", "x_pppoe_password": "wan-geheim"}]


def _handler(requests, policies, zones=None, groups=None, sites=None):
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/self/sites"):
            return httpx.Response(200, json={"data": sites or [{"name": "default"}, {"name": "../x"}]})
        if path.endswith("/firewall/zone"):
            return httpx.Response(200, json=ZONES if zones is None else zones)
        if path.endswith("/firewall-policies"):
            return httpx.Response(200, json=policies)
        if path.endswith("/rest/firewallgroup"):
            return httpx.Response(200, json={"data": GROUPS if groups is None else groups})
        if path.endswith("/rest/networkconf"):
            return httpx.Response(200, json={"data": NETWORKS})
        raise AssertionError(path)
    return handler


def _by_kind(result, kind):
    return [f["data"] for f in result["facts"] if f["kind"] == kind]


def test_only_get_with_api_key_no_redirect(monkeypatch):
    requests: list = []
    result = _run(_handler(requests, [_policy("p1", 1)]), monkeypatch)
    assert result["ok"]
    assert {r.method for r in requests} == {"GET"}
    assert all(r.headers["X-API-Key"] == KEY for r in requests)
    assert all(not {"cookie", "x-csrf-token", "authorization"} & set(r.headers) for r in requests)
    paths = sorted({r.url.path for r in requests})
    assert paths == ["/proxy/network/api/s/default/rest/firewallgroup", "/proxy/network/api/s/default/rest/networkconf",
                     "/proxy/network/api/self/sites",
                     "/proxy/network/v2/api/site/default/firewall-policies",
                     "/proxy/network/v2/api/site/default/firewall/zone"]


def test_parses_policies_and_flags(monkeypatch):
    pol = [_policy("p1", 10001, destination=_side(ZONE_B, port="80,443", port_matching_type="SPECIFIC")),
           _policy("p2", 2147483647, action="BLOCK", predefined=True, protocol="all", enabled=False)]
    policies = _by_kind(_run(_handler([], pol), monkeypatch), "policy")
    first, last = policies
    assert first["index"] == 10001 and first["destination"]["port"] == "80,443" and first["unsupported"] == []
    assert first["source"]["zoneId"] == ZONE_A and first["destination"]["zoneId"] == ZONE_B
    assert last["predefined"] and last["action"] == "BLOCK" and last["enabled"] is False


def test_zone_network_ids(monkeypatch):
    zones = _by_kind(_run(_handler([], []), monkeypatch), "zone")
    assert zones[0]["id"] == ZONE_A and zones[0]["networkIds"] == ["net-1", "net-2"] and zones[0]["name"] == "DMZ"


def test_groups_resolved_incl_range_and_unsupported_cidr(monkeypatch):
    groups = {g["id"]: g for g in _by_kind(_run(_handler([], []), monkeypatch), "group")}
    assert groups["g1"]["members"] == ["192.168.21.120-192.168.21.129"] and not groups["g1"]["unsupported"]
    assert groups["g2"]["groupType"] == "port-group" and groups["g2"]["members"] == ["22"]
    assert groups["g3"]["unsupported"] is True and groups["g3"]["members"] == []


def test_group_references_by_id(monkeypatch):
    pol = [_policy("p1", 1, destination=_side(ZONE_B, matching_target="IP", ip_group_id="g1", ips=[],
                                              port_matching_type="OBJECT", port_group_id="g2"))]
    dest = _by_kind(_run(_handler([], pol), monkeypatch), "policy")[0]["destination"]
    assert dest["ipGroupId"] == "g1" and dest["portGroupId"] == "g2" and dest["portType"] == "OBJECT"


def test_unsupported_reasons(monkeypatch):
    pol = [_policy("c", 1, connection_state_type="CUSTOM"),
           _policy("t", 2, schedule={"mode": "EVERY_WEEK"}),
           _policy("r", 3, action="REJECT"),
           _policy("o", 4, destination=_side(ZONE_B, port="1000-2000", port_matching_type="SPECIFIC")),
           _policy("n", 5, source=_side(ZONE_A, matching_target="NETWORK")),
           _policy("i", 6, match_ip_sec=True)]
    result = {p["id"]: p["unsupported"] for p in _by_kind(_run(_handler([], pol), monkeypatch), "policy")}
    assert all(result[k] for k in "ctroni")
    assert "Verbindungsstatus benutzerdefiniert" in result["c"] and "Zeitplan" in result["t"]


def test_drops_unknown_and_secret_fields(monkeypatch):
    pol = [_policy("p1", 1, secret="psk-123", pre_shared_key="psk-456", name="Name\x00\x07 ok")]
    result = _run(_handler([], pol), monkeypatch)
    text = str(result)
    assert "psk-" not in text and "geheimer Kommentar" not in text and KEY not in text
    assert _by_kind(result, "policy")[0]["name"] == "Name ok"


def test_error_text_has_no_body(monkeypatch):
    for status, text in ((401, "abgelehnt"), (403, "abgelehnt"), (404, "nicht verfügbar"),
                         (302, "Weiterleitung"), (500, "Status 500")):
        result = _run(lambda r, s=status: httpx.Response(s, text=KEY), monkeypatch)
        assert not result["ok"] and text in result["error"] and KEY not in result["error"], status
    assert not _run(lambda r: httpx.Response(200, text="nojson"), monkeypatch)["ok"]


def test_missing_or_bad_key_and_url(monkeypatch):
    assert not _run(_handler([], []), monkeypatch, key="")["ok"]
    assert not _run(_handler([], []), monkeypatch, key="bad key\n")["ok"]
    assert not _run(_handler([], []), monkeypatch, url="")["ok"]


def test_max_500_policies_is_unreadable_not_a_subset(monkeypatch):
    pol = [_policy(f"p{i}", i) for i in range(501)]
    result = _run(_handler([], pol), monkeypatch)
    assert not result["ok"] and result["facts"] == [] and "Zu viele" in result["error"]
    assert _run(_handler([], pol[:500]), monkeypatch)["ok"]


def test_zone_gets_only_subnets_from_networkconf(monkeypatch):
    result = _run(_handler([], [_policy("p1", 1)]), monkeypatch)
    zone = next(z for z in _by_kind(result, "zone") if z["id"] == ZONE_A)
    assert zone["cidrs"] == ["192.0.2.0/26", "192.0.2.64/26"]
    assert "wan-geheim" not in str(result)


def test_custom_state_without_new_is_not_unsupported(monkeypatch):
    pol = [_policy("inv", 1, connection_state_type="CUSTOM", connection_states=["INVALID"]),
           _policy("new", 2, connection_state_type="CUSTOM", connection_states=["NEW", "INVALID"])]
    by_id = {p["id"]: p for p in _by_kind(_run(_handler([], pol), monkeypatch), "policy")}
    assert by_id["inv"]["connectionState"] == "NO_NEW" and by_id["inv"]["unsupported"] == []
    assert by_id["new"]["unsupported"] == ["Verbindungsstatus benutzerdefiniert"]
