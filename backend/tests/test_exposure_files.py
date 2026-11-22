import asyncio

from app import exposure_files as ef
from app import pipeline

CADDY = """
{
    email admin@example.net
    admin off
}
(mtls) {
    tls {
        client_auth {
            mode require_and_verify
            trusted_ca_cert_file /etc/caddy/ca.pem
        }
    }
}
app1.example.net, App2.example.net:443 {
    import mtls
    basicauth { admin $2a$14$CADDYHASHSECRET }
    reverse_proxy 192.0.2.20:8080 192.0.2.21:8080 {
        header_up X-Token CADDYTOKENSECRET
    }
}
*.example.net {
    reverse_proxy unix//run/app.sock
}
app3.example.net {
    import /etc/caddy/extra.conf
    reverse_proxy https://user:CADDYPWSECRET@192.0.2.30:8443/path
}
:8080 {
    respond "hi"
}
"""

CLOUDFLARED = """
tunnel: 11111111-2222-3333-4444-555555555555
credentials-file: /etc/cloudflared/TUNNELSECRETFILE.json
token: CFTOKENSECRET
ingress:
  - hostname: app2.example.net
    service: http://localhost:8080
    originRequest:
      noTLSVerify: true
  - hostname: "*.example.net"
    service: http://192.0.2.20:80
  - hostname: app1.example.net
    service: https://192.0.2.21:8443
  - service: http_status:404
"""

DDCLIENT = """
daemon=300
use=web
protocol=cloudflare, zone=example.net, login=me@example.net, password='DDPWSECRET' \\
  home.example.net,vpn.example.net
protocol=dyndns2
server=ddns.example.org
usev6=if, if=eth0
login=user
password=DDPWSECRET2
v6.example.net
"""

SECRETS = ["CADDYHASHSECRET", "CADDYTOKENSECRET", "CADDYPWSECRET", "TUNNELSECRETFILE", "CFTOKENSECRET",
           "DDPWSECRET", "DDPWSECRET2", "me@example.net", "admin@example.net"]


def _data(facts):
    return {f["key"]: f["data"] for f in facts}


def test_caddy_sites_snippets_and_mtls():
    facts = _data(ef.parse_caddy(CADDY))
    assert set(facts) == {"app1.example.net", "app2.example.net", "app3.example.net", "*.example.net"}
    assert facts["app1.example.net"]["upstreams"] == ["192.0.2.20:8080", "192.0.2.21:8080"]
    assert facts["app1.example.net"]["mtls"] is True
    assert facts["app2.example.net"]["mtls"] is True
    assert facts["app3.example.net"]["mtls"] is False and facts["app3.example.net"]["imports"] is True
    assert facts["app3.example.net"]["upstreams"] == ["https://192.0.2.30:8443"]
    assert facts["*.example.net"]["upstreams"] == []  # unix socket dropped


def test_cloudflared_ingress_only():
    facts = _data(ef.parse_cloudflared(CLOUDFLARED))
    assert set(facts) == {"app2.example.net", "*.example.net", "app1.example.net"}  # catch-all dropped
    assert facts["app2.example.net"] == {"host": "app2.example.net", "origin": "http://localhost:8080",
                                         "tls_noverify": True}
    assert facts["app1.example.net"]["tls_noverify"] is False


def test_ddclient_blocks():
    facts = ef.parse_ddclient(DDCLIENT)
    assert [f["data"]["hosts"] for f in facts] == [["home.example.net", "vpn.example.net"], ["v6.example.net"]]
    assert facts[0]["data"]["provider"] == "cloudflare" and facts[0]["data"]["ipv6"] is False
    assert facts[1]["data"]["provider"] == "dyndns2 (ddns.example.org)" and facts[1]["data"]["ipv6"] is True


def test_no_secret_in_any_parsed_fact():
    out = str(ef.parse_caddy(CADDY)) + str(ef.parse_cloudflared(CLOUDFLARED)) + str(ef.parse_ddclient(DDCLIENT))
    for secret in SECRETS:
        assert secret not in out


def test_empty_and_garbage_input():
    for parser in (ef.parse_caddy, ef.parse_cloudflared, ef.parse_ddclient):
        assert parser("") == [] and parser("}}} {{{ \x00 ::") == []


def test_commands_are_fixed_constants_without_path():
    assert set(ef._FILE_COMMANDS) == {"cloudflared", "caddy", "ddclient"}
    assert all(cmd == "cat" for cmd in ef._FILE_COMMANDS.values())


def test_probe_rejects_unknown_source_and_missing_host():
    assert not asyncio.run(ef.probe("rm", "192.0.2.5", {}))["ok"]
    assert "Zielsystem" in asyncio.run(ef.probe("caddy", "", {}))["error"]


def test_probe_runs_only_the_constant_and_never_leaks_content(monkeypatch):
    import asyncssh
    ran: list = []

    class Result:
        stdout = CADDY

    class Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def run(self, command, **kwargs):
            ran.append(command)
            return Result()

    monkeypatch.setattr(asyncssh, "import_private_key", lambda *a: object())
    monkeypatch.setattr(asyncssh, "connect", lambda **kw: Conn())
    result = asyncio.run(ef.probe("caddy", "192.0.2.5", {"username": "ha"}, via="192.0.2.5"))
    assert ran == ["cat"] and result["ok"]
    assert all(f["data"]["via"] == "192.0.2.5" for f in result["facts"])

    Result.stdout = "x" * 10
    monkeypatch.setattr(ef, "_PARSERS", {"caddy": lambda t: 1 / 0})
    failed = asyncio.run(ef.probe("caddy", "192.0.2.5", {}))
    assert not failed["ok"] and "xxxx" not in failed["error"]


def _scan(temp_db, monkeypatch):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("test")))


def test_pipeline_isolation_stale_and_opt_in(temp_db, monkeypatch):
    system = temp_db.create_system({"kind": "vm", "name": "DMZ", "ip": "192.0.2.5"})
    caddy = temp_db.create_account({"systemId": system["id"], "label": "Caddy", "category": "exposure_caddy",
                                    "username": "ha", "allowProbe": 1})
    temp_db.create_account({"systemId": system["id"], "label": "Tunnel", "category": "exposure_cloudflared",
                            "username": "ha", "allowProbe": 1})
    temp_db.create_account({"systemId": system["id"], "label": "off", "category": "exposure_ddclient",
                            "username": "ha", "allowProbe": 0})
    calls: list = []

    async def fake(source, host, account, via=""):
        calls.append(source)
        if source == "cloudflared":
            return {"ok": False, "error": "SSH-Verbindung fehlgeschlagen", "facts": []}
        return {"ok": True, "error": "", "facts": [
            {"kind": "caddy_site", "key": "a.example.net", "data": {"host": "a.example.net", "via": via}}]}

    monkeypatch.setattr(pipeline.exposure_files, "probe", fake)
    _scan(temp_db, monkeypatch)
    assert sorted(calls) == ["caddy", "cloudflared"]  # no allowProbe -> never contacted
    assert [r["source"] for r in temp_db.list_exposure_facts()] == ["caddy"]  # the other source kept going

    temp_db.update_account(caddy["id"], {"allowProbe": 0})
    _scan(temp_db, monkeypatch)
    assert temp_db.list_exposure_facts() == []  # opt-in removed -> facts deleted
