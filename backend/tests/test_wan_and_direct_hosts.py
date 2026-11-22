"""WAN address from UniFi/FRITZ!Box, hosts pointing directly at the connection, and the HA log fallback."""
import asyncio

import httpx

from app import db, docs, exposure, fritz_wan, probe_auth

PUBLIC, OTHER = "8.8.4.4", "1.0.0.1"
_REAL_CLIENT = httpx.AsyncClient
SYSTEMS = [{"id": "dmz", "name": "Reverse Proxy", "kind": "vm", "ip": "192.168.40.10", "status": "online", "extra": {}}]


def F(kind, origin, /, stale=0, **data):
    return {"kind": kind, "source": origin, "data": data, "stale": stale, "lastSeen": "2026-01-01T00:00:00"}


FORWARD = F("portforward", "unifi_classic", proto="TCP", wanPort="443", destIp="192.168.40.10", destPort="443",
            enabled=True)
SCAN = F("portforward_scan", "unifi_classic", count=1)


def test_private_row_address_is_replaced_by_the_reported_public_one():
    facts = [F("wan_address", "unifi_classic", ip=PUBLIC, source="UniFi")]
    data = exposure.build_chains(facts, [], {"ip": "192.168.178.20", "type": "dhcp"})
    assert data["wan"]["ip"] == PUBLIC


def test_stale_address_is_ignored_and_a_mismatch_is_reported():
    stale = [F("wan_address", "fritzbox", stale=1, ip=OTHER, source="FRITZ!Box")]
    assert exposure.build_chains(stale, [], {"ip": PUBLIC})["hints"] == [
        "Quelle „fritzbox“ war beim letzten Scan nicht lesbar – Stand von 2026-01-01T00:00."]


def test_address_priority_interface_then_fritz_then_geo():
    geo = F("wan_address", "unifi_classic", ip=PUBLIC, source="UniFi", origin="geo")
    fritz = F("wan_address", "fritzbox", ip=OTHER, source="FRITZ!Box")
    data = exposure.build_chains([geo, fritz], [], {"ip": PUBLIC})
    assert data["wan"]["ip"] == OTHER and any("unterschiedliche" in h and "FRITZ!Box." in h for h in data["hints"])
    interface = F("wan_address", "unifi_classic", ip="9.9.9.9", source="UniFi", origin="interface")
    assert exposure.build_chains([geo, fritz, interface], [], None)["wan"]["ip"] == "9.9.9.9"
    only_geo = exposure.build_chains([geo], [], None)
    assert only_geo["wan"]["ip"] == PUBLIC and any("veraltet" in h for h in only_geo["hints"])


def test_stale_geo_address_does_not_make_a_host_direct():
    facts = [F("wan_address", "unifi_classic", ip=OTHER, source="UniFi", origin="geo"),
             F("wan_address", "fritzbox", ip=PUBLIC, source="FRITZ!Box"),
             F("dns", "public_dns", host="old.example.net", addrs=[OTHER], cname=""),
             F("dns", "public_dns", host="home.example.net", addrs=[PUBLIC], cname="")]
    assert [r["host"] for r in exposure.build_chains(facts, [], None)["direct"]] == ["home.example.net"]


def test_dyndns_cname_and_ddns_only_hosts_are_direct():
    facts = [F("wan_address", "unifi_classic", ip=PUBLIC, source="UniFi"), FORWARD, SCAN,
             F("cf_dns", "cloudflare", host="home2.example.net", type="CNAME", target="box.ddnss.example", proxied=False),
             F("dns", "public_dns", host="home2.example.net", addrs=[PUBLIC], cname="box.ddnss.example"),
             F("dns", "public_dns", host="box.ddnss.example", addrs=[PUBLIC], cname=""),
             F("cf_dns", "cloudflare", host="mail.example.net", type="A", target=OTHER, proxied=False),
             F("dns", "public_dns", host="mail.example.net", addrs=[OTHER], cname="")]
    data = exposure.build_chains(facts, SYSTEMS, None)
    assert [r["host"] for r in data["direct"]] == ["box.ddnss.example", "home2.example.net"]
    row = data["direct"][1]
    assert row["status"] == "aktiv" and row["target"] == "box.ddnss.example"
    assert row["forwards"][0]["systems"][0]["id"] == "dmz"
    assert [e["host"] for e in data["external"]] == ["mail.example.net"]
    assert any("Caddy" in h for h in data["hints"])
    assert {r["host"] for r in exposure.for_system(data, "dmz") if r["scope"] == "extern"} == {
        "box.ddnss.example", "home2.example.net"}


def test_direct_host_without_forward_is_orphaned_and_unknown_without_scan():
    host = [F("wan_address", "unifi_classic", ip=PUBLIC, source="UniFi"),
            F("dns", "public_dns", host="old.example.net", addrs=[PUBLIC], cname="")]
    assert exposure.build_chains([*host, SCAN], [], None)["direct"][0]["status"] == "verwaist"
    assert exposure.build_chains(host, [], None)["direct"][0]["status"] == "unklar"


def test_direct_hosts_are_rendered(temp_db):
    db.replace_exposure_facts("unifi_classic", "a", [
        {"kind": "wan_address", "key": "w", "data": {"ip": PUBLIC, "source": "UniFi"}},
        {"kind": "portforward", "key": "p", "data": {"proto": "TCP", "wanPort": "443", "destIp": "192.168.40.10",
                                                     "destPort": "443", "enabled": True}},
        {"kind": "portforward_scan", "key": "scan", "data": {"count": 1}}])
    db.replace_exposure_facts("public_dns", "b", [
        {"kind": "dns", "key": "h", "data": {"host": "home2.example.net", "addrs": [PUBLIC], "cname": "x.ddnss.example"}}])
    body = docs._exposure_section()
    assert "Direkt über den Internetanschluss" in body and "home2.example.net" in body and "aktiv" in body


def _patch_fritz(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(fritz_wan.httpx, "AsyncClient", lambda **k: _REAL_CLIENT(transport=transport, **k))


def test_fritz_reads_the_address_with_one_action_and_no_credentials(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=f"<NewExternalIPAddress>{PUBLIC}</NewExternalIPAddress>")

    _patch_fritz(monkeypatch, handler)
    assert asyncio.run(fritz_wan.probe("192.168.178.1")) == {"ok": True, "error": "", "ip": PUBLIC}
    assert len(seen) == 1 and seen[0].url.path == "/igdupnp/control/WANIPConn1"
    assert seen[0].headers["SOAPAction"].endswith("#GetExternalIPAddress")
    assert "authorization" not in seen[0].headers


def test_fritz_rejects_private_and_failed_answers(monkeypatch):
    _patch_fritz(monkeypatch, lambda r: httpx.Response(200, text="<NewExternalIPAddress>192.168.1.2</NewExternalIPAddress>"))
    assert not asyncio.run(fritz_wan.probe("192.168.178.1"))["ok"]
    _patch_fritz(monkeypatch, lambda r: httpx.Response(500, text="SECRET-BODY"))
    result = asyncio.run(fritz_wan.probe("192.168.178.1"))
    assert not result["ok"] and "SECRET-BODY" not in result["error"]


def test_error_log_falls_back_to_the_redacted_system_log(monkeypatch):
    calls = []

    async def fake_get(url, account, path, as_text=False):
        return {"ok": False, "error": "HTTP 404"}

    async def fake_ws(url, account, msg_type, payload):
        calls.append(msg_type)
        return {"ok": True, "data": [
            {"timestamp": 200.0, "level": "ERROR", "name": "new", "count": 2,
             "message": ["Authorization: Bearer topsecrettoken"], "exception": "Traceback line"},
            {"timestamp": 100.0, "level": "WARNING", "name": "old", "count": 1, "message": ["older"], "exception": ""}]}

    monkeypatch.setattr(probe_auth, "_ha_get", fake_get)
    monkeypatch.setattr(probe_auth, "_ha_ws_call", fake_ws)
    result = asyncio.run(probe_auth.ha_error_log("http://ha:8123", {}))
    assert result["ok"] and calls == ["system_log/list"]
    assert "topsecrettoken" not in result["text"] and "Traceback line" in result["text"]
    assert result["text"].index("older") < result["text"].index("ERROR new")
    assert "Systemprotokoll" in result["note"]
