from app import docker_probe, exposure


def test_env_allowlist_and_hostname_validation():
    env = ["DOMAINS=home.example.net, *.bad.example.net,nope", "CLOUDFLARE_API_TOKEN=SECRETTOKEN",
           "IP6_PROVIDER=none", "PASSWORD=hunter2"]
    fact = docker_probe.ddns_fact("favonia/cloudflare-ddns:latest", env, "192.0.2.20")
    assert fact["data"] == {"client": "cloudflare-ddns", "provider": "Cloudflare", "hosts": ["home.example.net"],
                            "ipv4": True, "ipv6": False, "via": "192.0.2.20"}
    assert "SECRETTOKEN" not in str(fact) and "hunter2" not in str(fact)


def test_unknown_image_is_ignored():
    assert docker_probe.ddns_fact("nginx:1", ["DOMAINS=a.example.net"], "192.0.2.20") is None


def test_ddclient_without_env_has_no_hosts():
    fact = docker_probe.ddns_fact("linuxserver/ddclient", [], "192.0.2.20")
    assert fact["data"]["hosts"] == [] and fact["data"]["provider"] == "ddclient" and not fact["data"]["ipv6"]


def test_resolution_against_wan_ip():
    facts = [
        {"kind": "ddns", "source": "docker_ddns", "data": {"client": "x", "provider": "Cloudflare", "ipv4": True,
         "ipv6": False, "via": "192.0.2.20", "hosts": ["home.example.net", "old.example.net"]}},
        {"kind": "dns", "data": {"host": "home.example.net", "addrs": ["198.51.100.1"]}},
        {"kind": "dns", "data": {"host": "old.example.net", "addrs": ["198.51.100.99"]}},
    ]
    result = exposure.build_chains(facts, [], {"ip": "198.51.100.1"})
    rows = {r["host"]: r["resolvesToWan"] for r in result["ddns"][0]["hosts"]}
    assert rows == {"home.example.net": True, "old.example.net": False}
    assert any("old.example.net" in h for h in result["hints"])


def test_external_hosted_and_tunnel_status():
    facts = [
        {"kind": "cf_dns", "data": {"host": "shop.example.net", "type": "A", "target": "203.0.113.50",
                                    "proxied": True, "provider": "web.hoster.example"}},
        {"kind": "cf_dns", "data": {"host": "home.example.net", "type": "A", "target": "198.51.100.1", "proxied": False}},
        {"kind": "cf_dns", "data": {"host": "app.example.net", "type": "CNAME", "target": "abc.cfargotunnel.com",
                                    "proxied": True}},
        {"kind": "cf_tunnel", "data": {"id": "abc", "name": "home", "status": "down"}},
    ]
    result = exposure.build_chains(facts, [], {"ip": "198.51.100.1"})
    assert [e["host"] for e in result["external"]] == ["shop.example.net"]
    assert result["external"][0]["provider"] == "web.hoster.example"
    assert any("nicht verbunden" in h for h in result["hints"])
    # without the WAN address nothing is called external (unclear, not wrong)
    assert exposure.build_chains(facts, [], None)["external"] == []
