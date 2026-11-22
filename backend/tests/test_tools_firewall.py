import asyncio
import json

from app import db, prompts, tools


def _call(name, args):
    return json.loads(asyncio.run(tools.dispatch(name, args)))


def _seed(rule_name="Allow HTTPS", name_dmz="DMZ"):
    def zone(i, n, nets):
        return {"kind": "zone", "key": f"zone:d:{i}", "data": {"id": i, "name": n, "zoneKey": "", "networkIds": nets}}

    def side(z, **kw):
        return {"zoneId": z, "target": "ANY", "ips": [], "ipGroupId": "", "portType": "ANY", "port": "",
                "portGroupId": "", **kw}
    pol = {"id": "p1", "name": rule_name, "index": 10, "enabled": True, "predefined": False, "action": "ALLOW",
           "protocol": "tcp", "ipVersion": "BOTH", "connectionState": "ALL", "source": side("z1"),
           "destination": side("z2", portType="SPECIFIC", port="443"), "unsupported": []}
    db.replace_firewall_facts("unifi", "acc", [zone("z1", name_dmz, ["n1"]), zone("z2", "Server", ["n2"]),
                                                {"kind": "policy", "key": "policy:d:p1", "data": pol}])
    nets = [{"kind": "network", "source": "unifi", "siteExternalId": "s", "siteName": "d", "externalId": e,
             "name": e, "facts": {"cidr": c}} for e, c in (("n1", "192.0.2.0/26"), ("n2", "192.0.2.64/26"))]
    db.sync_network_resources("acc", nets, [("s", "network")])


def test_invalid_port_protocol_unknown_and_same_system(temp_db):
    assert "error" in _call("check_firewall_path", {"von": "192.0.2.1", "nach": "192.0.2.70", "port": 0})
    assert "error" in _call("check_firewall_path", {"von": "192.0.2.1", "nach": "192.0.2.70", "port": 80, "protokoll": "gre"})
    assert "nope" in _call("check_firewall_path", {"von": "nope", "nach": "192.0.2.70", "port": 80})["error"]
    assert "dasselbe" in _call("check_firewall_path", {"von": "192.0.2.7", "nach": "192.0.2.7", "port": 80})["error"]


def test_without_facts_is_unclear_never_allowed(temp_db):
    out = _call("check_firewall_path", {"von": "192.0.2.1", "nach": "192.0.2.70", "port": 443})
    assert out["verdict"] == "unklar" and out["stations"][0]["source"] == "UniFi" and "Proxmox" in out["notes"]


def test_list_rules_needs_arguments(temp_db):
    assert "error" in _call("list_firewall_rules", {})


def test_schema_prompt_and_mcp_mention_tool():
    names = {t["name"] for t in tools.TOOL_DEFINITIONS}
    assert {"check_firewall_path", "list_firewall_rules"} <= names
    assert "check_firewall_path" in prompts.CHAT_SYSTEM
    assert "check_firewall_path" in json.dumps(tools.TOOL_DEFINITIONS)


def test_tools_import_only_eval_not_sources():
    from test_exposure_boundaries import _imports
    assert "firewall_eval" in _imports("tools")
    assert not _imports("tools") & {"firewall_unifi", "firewall_nft", "remote_admin", "docker_admin", "proxmox_admin"}


def test_blocked_unclear_allowed_over_the_tool_and_output_is_clean(temp_db):
    _seed(rule_name="x\ny" + "z" * 200)
    out = _call("check_firewall_path", {"von": "192.0.2.10", "nach": "192.0.2.70", "port": 443})
    st = out["stations"][0]
    assert st["verdict"] == "erlaubt" and len(st["rule"]["name"]) <= 80 and "\n" not in st["rule"]["name"]
    assert out["verdict"] == "unklar"  # destination host firewall not connected
    out = _call("check_firewall_path", {"von": "192.0.2.10", "nach": "192.0.2.70", "port": 22})
    assert out["stations"][0]["verdict"] == "unklar"  # no default rule stored
    rules = _call("list_firewall_rules", {"von": "DMZ", "nach": "192.0.2.70"})
    assert rules["zonePair"] == "DMZ -> Server" and rules["rules"][0]["position"] == "Index 10"
    text = json.dumps(out) + json.dumps(rules)
    assert "sourceAccountId" not in text and "secret" not in text.lower()
