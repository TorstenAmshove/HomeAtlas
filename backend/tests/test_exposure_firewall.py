from app import firewall_eval as ev

SYSTEMS = [{"id": "p", "name": "proxy", "ip": "192.0.2.10", "kind": "server"},
           {"id": "b", "name": "backend", "ip": "192.0.2.70", "kind": "server"}]
NETRES = [{"kind": "network", "externalId": "n1", "facts": {"cidr": "192.0.2.0/26"}},
          {"kind": "network", "externalId": "n2", "facts": {"cidr": "192.0.2.64/26"}}]


def _chain(status="aktiv"):
    return [{"host": "x.example.net", "hints": [], "paths": [{"status": status, "steps": [
        {"label": "192.0.2.10:443", "systems": [{"id": "p", "name": "proxy"}]},
        {"label": "192.0.2.70:8080", "systems": [{"id": "b", "name": "backend"}]},
        {"label": "unbekannt", "systems": []}]}]}]


def _facts():
    def side(z):
        return {"zoneId": z, "target": "ANY", "ips": [], "ipGroupId": "", "portType": "ANY", "port": "", "portGroupId": ""}
    zones = [{"source": "unifi", "kind": "zone", "key": k, "stale": 0, "data": {"id": k, "name": k, "zoneKey": "", "networkIds": [n]}}
             for k, n in (("z1", "n1"), ("z2", "n2"))]
    pol = {"source": "unifi", "kind": "policy", "key": "p", "stale": 0, "data": {
        "id": "p", "name": "Block All Traffic", "index": 2147483647, "enabled": True, "predefined": True,
        "action": "BLOCK", "protocol": "all", "ipVersion": "BOTH", "connectionState": "ALL",
        "source": side("z1"), "destination": side("z2"), "unsupported": []}}
    return zones + [pol]


def test_each_step_has_result_and_no_facts_is_unclear():
    chains = ev.annotate_chains(_chain(), [], SYSTEMS, NETRES)
    steps = chains[0]["paths"][0]["steps"]
    assert all(s["firewall"]["verdict"] == "unklar" for s in steps)
    assert "Portweiterleitung" in steps[0]["firewall"]["reason"]


def test_blocked_configured_path_gets_hint():
    chains = ev.annotate_chains(_chain(), _facts(), SYSTEMS, NETRES)
    steps = chains[0]["paths"][0]["steps"]
    assert steps[1]["firewall"]["verdict"] == "blockiert"
    assert steps[2]["firewall"]["verdict"] == "unklar"
    assert any("Firewall blockiert" in h for h in chains[0]["hints"])


def test_blocked_but_orphan_path_has_no_hint():
    chains = ev.annotate_chains(_chain("verwaist"), _facts(), SYSTEMS, NETRES)
    assert chains[0]["hints"] == []


def _via_chain(label="192.0.2.70:8080"):
    return [{"host": "x.example.net", "hints": [], "paths": [{"status": "aktiv", "via": "192.0.2.10", "steps": [
        {"label": label, "systems": [{"id": "b", "name": "backend"}], "fromVia": True}]}]}]


def test_single_step_is_judged_from_the_proxy():
    chains = ev.annotate_chains(_via_chain(), _facts(), SYSTEMS, NETRES)
    assert chains[0]["paths"][0]["steps"][0]["firewall"]["verdict"] == "blockiert"
    assert any("Firewall blockiert" in h for h in chains[0]["hints"])


def test_gateway_allow_is_named_while_host_firewall_is_unknown():
    facts = _facts()
    facts[-1]["data"]["action"] = "ALLOW"
    fw = ev.annotate_chains(_via_chain(), facts, SYSTEMS, NETRES)[0]["paths"][0]["steps"][0]["firewall"]
    assert fw["verdict"] == "unklar" and fw["reason"].startswith("UniFi erlaubt") and "nftables" in fw["reason"]
