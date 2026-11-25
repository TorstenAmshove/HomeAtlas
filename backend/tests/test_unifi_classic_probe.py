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


def _handler(requests, forwards, health, sites=None, stations=None, profiles=None, networks=None):
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
                {"name": "LAN", "purpose": "corporate"}] + (networks or [])})
        if path.endswith("/rest/portconf"):
            return httpx.Response(200, json={"data": profiles or []})
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


NETS = [{"_id": "n10", "name": "Default", "purpose": "corporate", "x_passphrase": "WLANSECRET"},
        {"_id": "n20", "name": "IoT", "purpose": "corporate", "vlan": 20},
        {"_id": "n30", "name": "Gäste", "purpose": "corporate", "vlan": 30}]
PROFILES = [{"_id": "p-all", "name": "All", "native_networkconf_id": "n10", "tagged_vlan_mgmt": "auto"},
            {"_id": "p-iot", "name": "IoT-Port", "native_networkconf_id": "n20", "tagged_vlan_mgmt": "block_all"},
            {"_id": "p-cust", "name": "Trunk", "native_networkconf_id": "n10", "tagged_vlan_mgmt": "custom",
             "tagged_networkconf_ids": ["n20"]}]


def _ports(devices, monkeypatch, profiles=PROFILES, networks=NETS):
    result = _run(_handler([], [], devices, profiles=profiles, networks=networks), monkeypatch)
    assert result["ok"] and result["portsOk"]
    return result, {p["port"]: p for sw in result["switches"] for p in sw["ports"]}


def test_probe_switch_ports_override_profile_default(monkeypatch):
    switch = {"type": "usw", "mac": "AA:BB:CC:00:00:01", "port_table": [
        {"port_idx": 1, "name": "Port 1", "portconf_id": "p-all"},
        {"port_idx": 2, "name": "Büro | PC", "portconf_id": "p-all"},
        {"port_idx": 3, "name": "Direkt", "native_networkconf_id": "n30", "tagged_vlan_mgmt": "auto",
         "excluded_networkconf_ids": ["n20", "gone"]},
        {"port_idx": 4, "name": "Ohne"}],
        "port_overrides": [{"port_idx": 2, "portconf_id": "p-iot"},
                           {"port_idx": 1, "tagged_vlan_mgmt": "block_all"}]}
    result, ports = _ports([switch, {"type": "uap", "mac": "aa:bb:cc:00:00:02", "port_table": [{"port_idx": 1}]}],
                           monkeypatch)
    assert [(s["site"], s["mac"]) for s in result["switches"]] == [("default", "aa:bb:cc:00:00:01")]
    assert ports[1]["native"] == {"vlan": 1, "name": "Default", "known": True, "default": True}  # = VLAN 1
    assert ports[1]["tagged"]["mode"] == "none" and ports[1]["profile"] == "All"
    assert ports[2]["name"] == "Büro | PC" and ports[2]["profile"] == "IoT-Port"
    assert ports[2]["native"]["vlan"] == 20 and ports[2]["tagged"]["mode"] == "none"
    assert ports[3]["tagged"] == {"mode": "all", "vlans": [], "excluded": [
        {"vlan": 20, "name": "IoT"}, {"vlan": None, "name": ""}]}
    assert ports[4]["native"] == {"vlan": None, "name": "", "known": True} and ports[4]["tagged"]["mode"] == ""


def test_port_tagged_modes(monkeypatch):
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01", "port_table": [
        {"port_idx": 1, "portconf_id": "p-cust"}, {"port_idx": 2, "tagged_vlan_mgmt": "weird"},
        {"port_idx": 3, "portconf_id": "p-all"}, {"port_idx": 4, "portconf_id": "p-iot"}]}
    _, ports = _ports([switch], monkeypatch)
    assert [ports[i]["tagged"]["mode"] for i in (1, 2, 3, 4)] == ["custom", "custom", "all", "none"]
    assert all(p["tagged"]["vlans"] == [] for p in ports.values())


def test_unknown_network_id(monkeypatch):
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01", "port_table": [
        {"port_idx": 1, "native_networkconf_id": "nope"}]}
    _, ports = _ports([switch], monkeypatch)
    assert ports[1]["native"] == {"vlan": None, "name": "", "known": False}


def test_probe_ports_keep_only_allowlisted_fields(monkeypatch):
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01", "name": "SECRETNAME", "ip": "10.9.9.9",
              "x_authkey": "AUTHSECRET", "port_table": [
                  {"port_idx": 1, "name": "P", "portconf_id": "p-all", "rx_bytes": 99, "x_foo": "XSECRET",
                   "mac": "de:ad:be:ef:00:01", "ip": "10.1.1.1"}]}
    result, _ = _ports([switch], monkeypatch)
    text = str(result["switches"])
    for secret in ("SECRETNAME", "10.9.9.9", "AUTHSECRET", "XSECRET", "de:ad", "WLANSECRET", "p-all", "n10"):
        assert secret not in text
    assert set(result["switches"][0]["ports"][0]) == {"port", "name", "profile", "native", "defaultVlan", "tagged"}


@pytest.mark.parametrize("response", [
    httpx.Response(404, text=KEY), httpx.Response(403, text=KEY), httpx.Response(429, text=KEY),
    httpx.Response(500, text=KEY), httpx.Response(400, text=KEY), httpx.Response(401, text=KEY),
    httpx.Response(200, text="no json"), httpx.Response(200, json={"data": {"a": 1}})])
def test_portconf_errors_keep_other_sources(monkeypatch, response):
    fw = [{"proto": "tcp", "dst_port": "1", "fwd": "192.0.2.1", "fwd_port": "1"}]

    def handler(request):
        if request.url.path.endswith("/rest/portconf"):
            return response
        return _handler([], fw, [{"type": "usw", "mac": "aa:bb:cc:00:00:01", "port_table": []}],
                        stations=[WIRED])(request)

    result = _run(handler, monkeypatch)
    assert result["ok"] and not result["portsOk"] and result["switches"] == []
    assert len(result["forwards"]) == 2 and len(result["wans"]) == 2 and len(result["clients"]) == 1
    assert any("Port-VLANs" in w for w in result["warnings"]) and KEY not in str(result)


def test_ports_cap_128_and_profiles_cap_200_single_warning(monkeypatch):
    profiles = [{"_id": f"p{i}", "name": f"P{i}"} for i in range(probe_mod._MAX_PROFILES + 5)]
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01",
              "port_table": [{"port_idx": i} for i in range(1, probe_mod._MAX_PORTS + 6)]}
    result, ports = _ports([switch], monkeypatch, profiles=profiles)
    assert len(ports) == probe_mod._MAX_PORTS
    assert sum("Port-Profile" in w for w in result["warnings"]) == 1
    assert sum("Ports an einem Switch" in w for w in result["warnings"]) == 1


def test_profile_not_resolved_across_sites(monkeypatch):
    def handler(request):
        if request.url.path == "/proxy/network/api/s/b2/rest/portconf":
            return httpx.Response(200, json={"data": []})
        return _handler([], [], [{"type": "usw", "mac": "aa:bb:cc:00:00:01",
                                  "port_table": [{"port_idx": 1, "portconf_id": "p-iot"}]}],
                        sites=[{"name": "default"}, {"name": "b2"}], profiles=PROFILES, networks=NETS)(request)

    result = _run(handler, monkeypatch)
    by_site = {sw["site"]: sw["ports"][0] for sw in result["switches"]}
    assert by_site["default"]["profile"] == "IoT-Port" and by_site["b2"]["profile"] == ""
    assert by_site["b2"]["tagged"]["mode"] == ""


def test_only_usw_devices_and_bad_port_idx_ignored(monkeypatch):
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01", "port_table": [
        {"port_idx": 0}, {"port_idx": "1"}, {"port_idx": True}, {"port_idx": 1}, {"port_idx": 1, "name": "dup"}, "x"]}
    nomac = {"type": "usw", "port_table": [{"port_idx": 1}]}
    result, ports = _ports([switch, nomac, {"type": "udm", "mac": "aa:bb:cc:00:00:09", "port_table": [{"port_idx": 1}]}],
                           monkeypatch)
    assert list(ports) == [1] and len(result["switches"]) == 1


def test_default_network_flag():
    from app.unifi_classic_probe import _networks
    nets = _networks([
        {"_id": "wan", "name": "WAN", "purpose": "wan"},
        {"_id": "d", "name": "Default", "purpose": "corporate"},
        {"_id": "d2", "name": "Zweites ohne VLAN", "purpose": "corporate"},
        {"_id": "v1", "name": "Explizit 1", "purpose": "corporate", "vlan": 1},
        {"_id": "g", "name": "Gast ohne VLAN", "purpose": "guest"},
        {"_id": "v20", "name": "IoT", "purpose": "corporate", "vlan": 20},
    ])
    assert "wan" not in nets
    assert nets["d"] == {"vlan": 1, "name": "Default", "default": True}
    assert [k for k, n in nets.items() if n.get("default")] == ["d"]  # only the first candidate
    assert nets["v1"] == {"vlan": 1, "name": "Explizit 1"}
    assert "default" not in nets["g"] and "default" not in nets["v20"]


def test_switch_ports_default_vlan(monkeypatch):
    switch = {"type": "usw", "mac": "aa:bb:cc:00:00:01", "port_table": [
        {"port_idx": 1, "portconf_id": "p-all"},
        {"port_idx": 2, "native_networkconf_id": "n20", "tagged_vlan_mgmt": "auto",
         "excluded_networkconf_ids": ["n10", "n30"]}]}
    _, ports = _ports([switch], monkeypatch)
    assert ports[1]["defaultVlan"] == 1 and ports[2]["defaultVlan"] == 1
    assert ports[1]["native"]["default"] is True
    assert "default" not in ports[2]["native"]
    assert ports[2]["tagged"]["excluded"] == [{"vlan": 1, "name": "Default", "default": True},
                                              {"vlan": 30, "name": "Gäste"}]

    nets_without_default = [n for n in NETS if n["_id"] != "n10"]
    _, ports = _ports([switch], monkeypatch, networks=nets_without_default)
    assert ports[1]["defaultVlan"] is None
