from app import exposure


def F(kind, source, **data):
    return {"kind": kind, "source": source, "data": data, "stale": 0, "lastSeen": "2026-01-01T00:00:00"}


SYSTEMS = [
    {"id": "h", "name": "docker-host", "kind": "server", "ip": "192.0.2.20", "status": "online", "extra": {}},
    {"id": "c2", "name": "app2", "kind": "container", "ip": "192.0.2.20", "status": "online",
     "extra": {"docker": {"portMappings": ["0.0.0.0:8080 -> 80/tcp"]}}},
    {"id": "c3", "name": "app3", "kind": "container", "ip": "192.0.2.20", "status": "offline",
     "extra": {"docker": {"portMappings": ["0.0.0.0:8081 -> 80/tcp"]}}},
]
WAN = {"ip": "198.51.100.7", "type": "dhcp"}


def tunnel(host, origin="http://192.0.2.20:8080"):
    return F("tunnel_ingress", "cloudflared", host=host, origin=origin, via="192.0.2.30")


def caddy(host, up="192.0.2.20:8080", **kw):
    return F("caddy_site", "caddy", host=host, upstreams=[up], mtls=kw.get("mtls", False), via="192.0.2.40")


def chain_for(facts, host="app2.example.net", wan=WAN):
    data = exposure.build_chains(facts, SYSTEMS, wan)
    return next(c for c in data["chains"] if c["host"] == host)


def test_full_chain_to_container_with_mtls():
    facts = [tunnel("app2.example.net"),
             F("cf_dns", "cloudflare", host="app2.example.net", type="CNAME", target="x.cfargotunnel.com", proxied=True),
             F("cf_waf_mtls", "cloudflare", host="app2.example.net")]
    chain = chain_for(facts)
    path = chain["paths"][0]
    assert path["status"] == "aktiv" and path["mtls"] and chain["cloudflare"]
    assert path["steps"][0]["systems"][0]["name"] == "app2"


def test_path_status_duplicate_caddy_orphaned_tunnel_active():
    facts = [tunnel("app2.example.net"), caddy("app2.example.net"),
             F("cf_dns", "cloudflare", host="app2.example.net", type="CNAME", target="x.cfargotunnel.com", proxied=True),
             F("dns", "dns", host="app2.example.net", addrs=["104.0.0.1"]),
             F("portforward", "unifi", proto="tcp", wanPort=443, destIp="192.0.2.99", destPort=443, enabled=True)]
    chain = chain_for(facts)
    status = {p["source"]: p["status"] for p in chain["paths"]}
    assert status == {"tunnel": "aktiv", "caddy": "verwaist"}
    assert any("entfernen oder dokumentieren" in h and "DMZ-Proxy" in h for h in chain["hints"])


def test_path_status_unclear_without_data_and_with_stale():
    assert chain_for([caddy("app2.example.net")])["paths"][0]["status"] == "unklar"
    stale = tunnel("app2.example.net")
    stale["stale"] = 1
    facts = [stale, F("cf_dns", "cloudflare", host="app2.example.net", type="A", target="198.51.100.7")]
    assert chain_for(facts)["paths"][0]["status"] == "unklar"


def test_caddy_active_via_wan_ip_and_forward():
    facts = [caddy("app2.example.net"), F("dns", "dns", host="app2.example.net", addrs=["198.51.100.7"]),
             F("portforward", "unifi", proto="tcp", wanPort=443, destIp="192.0.2.40", destPort=443, enabled=True)]
    assert chain_for(facts)["paths"][0]["status"] == "aktiv"


def test_correlation_shared_ip_loopback_none_and_stopped():
    facts = [tunnel("a.example.net", "http://localhost:8081"), tunnel("b.example.net", "http://192.0.2.77:80"),
             tunnel("c.example.net", "192.0.2.20:8080")]
    facts[0]["data"]["via"] = "192.0.2.20"
    data = exposure.build_chains(facts, SYSTEMS, WAN)
    by = {c["host"]: c for c in data["chains"]}
    assert by["a.example.net"]["paths"][0]["steps"][0]["systems"][0]["name"] == "app3"
    assert any("nicht erreichbar" in h for h in by["a.example.net"]["hints"])
    assert by["b.example.net"]["paths"][0]["steps"][0]["inInventory"] is False
    assert any("nicht im Inventar" in h for h in by["b.example.net"]["hints"])
    assert by["c.example.net"]["paths"][0]["steps"][0]["systems"][0]["name"] == "app2"


def test_wildcard_case_ipv6_and_unix():
    facts = [tunnel("*.example.net"), tunnel("App2.Example.NET.", "http://[::1]:8080"),
             caddy("x.example.net", "unix:/run/x.sock")]
    facts[1]["data"]["via"] = "192.0.2.20"
    hosts = [c["host"] for c in exposure.build_chains(facts, SYSTEMS, WAN)["chains"]]
    assert hosts == ["app2.example.net", "x.example.net"]


def test_cycle_terminates():
    facts = [caddy("a.example.net", "b.example.net:443"), caddy("b.example.net", "a.example.net:443")]
    chain = chain_for(facts, "a.example.net")
    assert len(chain["paths"][0]["steps"]) <= 4


def test_external_hosted():
    facts = [F("cf_dns", "cloudflare", host="blog.example.net", type="A", target="203.0.113.9", provider="webspace.example"),
             F("cf_dns", "cloudflare", host="home.example.net", type="A", target="198.51.100.7")]
    data = exposure.build_chains(facts, SYSTEMS, WAN)
    assert [e["host"] for e in data["external"]] == ["blog.example.net"]
    assert exposure.build_chains(facts, SYSTEMS, None)["external"] == []


def test_ddns_and_forward_hints():
    facts = [F("ddns", "ddclient", client="ddclient", provider="dyndns", hosts=["home.example.net"], ipv4=True,
               ipv6=False, via="192.0.2.20"),
             F("dns", "dns", host="home.example.net", addrs=["203.0.113.1"]),
             F("portforward", "unifi", proto="tcp", wanPort=22, destIp="192.0.2.99", destPort=22, enabled=True)]
    data = exposure.build_chains(facts, SYSTEMS, WAN)
    assert data["ddns"][0]["hosts"][0]["resolvesToWan"] is False
    assert any("zeigt nicht auf die WAN-IP" in h for h in data["hints"])
    assert any("kein Ziel im Inventar" in h for h in data["hints"])


def test_traefik_internal():
    facts = [F("traefik_router", "traefik", hosts=["x.lan.example.org"], service="http://192.0.2.20:8080",
               resolver="dns", middlewares=["auth"], tls=True)]
    row = exposure.build_chains(facts, SYSTEMS, WAN)["internal"][0]
    assert row["systems"][0]["name"] == "app2" and row["middlewares"] == ["auth"]
