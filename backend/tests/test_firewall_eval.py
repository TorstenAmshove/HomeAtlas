"""Path evaluation over prepared fact sets (#106 part C). Documentation addresses (192.0.2.0/24 ...)."""
from app import firewall_eval as ev

NETRES = [
    {"kind": "network", "externalId": "n-dmz", "facts": {"cidr": "192.0.2.0/26"}},
    {"kind": "network", "externalId": "n-srv", "facts": {"cidr": "192.0.2.64/26"}},
    {"kind": "network", "externalId": "n-lan", "facts": {"cidr": "192.0.2.128/26"}},
]


def _side(zone, **kw):
    return {"zoneId": zone, "target": "ANY", "ips": [], "ipGroupId": "", "portType": "ANY", "port": "",
            "portGroupId": "", **kw}


def _f(source, kind, data, stale=0):
    return {"source": source, "kind": kind, "key": str(id(data)), "data": data, "stale": stale}


def _zones():
    return [_f("unifi", "zone", {"id": "z-dmz", "name": "DMZ", "zoneKey": "dmz", "networkIds": ["n-dmz"]}),
            _f("unifi", "zone", {"id": "z-srv", "name": "Server", "zoneKey": "", "networkIds": ["n-srv"]}),
            _f("unifi", "zone", {"id": "z-lan", "name": "LAN", "zoneKey": "internal", "networkIds": ["n-lan"]}),
            _f("unifi", "zone", {"id": "z-ext", "name": "External", "zoneKey": "external", "networkIds": []})]


def _pol(name, index, action, src="z-dmz", dst="z-srv", **kw):
    data = {"id": name, "name": name, "index": index, "enabled": True, "predefined": False, "action": action,
            "protocol": "tcp", "ipVersion": "BOTH", "connectionState": "ALL",
            "source": _side(src), "destination": _side(dst, portType="SPECIFIC", port="443"), "unsupported": []}
    data.update(kw)
    return _f("unifi", "policy", data)


def _default(src="z-dmz", dst="z-srv"):
    return _pol("Block All Traffic", 2147483647, "BLOCK", src, dst, protocol="all",
                destination=_side(dst))


def _run(facts, port=443, proto="tcp", src="192.0.2.10", dst="192.0.2.70", dst_sys="", src_sys=""):
    a = {"ip": src, "systemId": src_sys, "label": "A"}
    b = {"ip": dst, "systemId": dst_sys, "label": "B"}
    return ev.evaluate_path(a, b, port, proto, facts, NETRES)


def _unifi_station(out):
    return out["stations"][0]


def test_dmz_to_server_blocked_with_rule():
    facts = _zones() + [_pol("Allow HTTPS", 10000, "ALLOW"), _default()]
    out = _run(facts, port=22)
    st = _unifi_station(out)
    assert out["verdict"] == "blockiert" and st["verdict"] == "blockiert" and st["source"] == "UniFi"
    assert st["rule"]["name"] == "Standard: alles blockieren" and st["rule"]["position"] is None


def test_allowed_port_with_unknown_host_firewall_stays_unclear():
    facts = _zones() + [_pol("Allow HTTPS", 10000, "ALLOW"), _default()]
    out = _run(facts)
    st = _unifi_station(out)
    assert st["verdict"] == "erlaubt" and st["rule"] == {"name": "Allow HTTPS", "position": "Index 10000"}
    assert out["verdict"] == "unklar"  # destination is no known system: never "allowed" on a guess


def test_first_match_wins_by_index_and_disabled_skipped():
    facts = _zones() + [_pol("Block 443", 5, "BLOCK"), _pol("Allow", 10, "ALLOW"), _default()]
    assert _unifi_station(_run(facts))["rule"]["name"] == "Block 443"
    facts = _zones() + [_pol("Block 443", 5, "BLOCK", enabled=False), _pol("Allow", 10, "ALLOW"), _default()]
    assert _unifi_station(_run(facts))["verdict"] == "erlaubt"


def test_equal_index_unclear():
    facts = _zones() + [_pol("a", 5, "ALLOW"), _pol("b", 5, "BLOCK")]
    assert _unifi_station(_run(facts))["verdict"] == "unklar"


def test_respond_only_not_matching():
    facts = _zones() + [_pol("ret", 5, "ALLOW", connectionState="RESPOND_ONLY"), _default()]
    assert _unifi_station(_run(facts))["verdict"] == "blockiert"


def test_unsupported_before_match_unclear():
    facts = _zones() + [_pol("timed", 5, "ALLOW", unsupported=["Zeitplan"]), _default()]
    st = _unifi_station(_run(facts))
    assert st["verdict"] == "unklar" and "Zeitplan" in st["reason"]


def test_groups_ranges_and_unknown_group():
    group = _f("unifi", "group", {"id": "g1", "name": "g", "groupType": "address-group",
                                  "members": ["192.0.2.5-192.0.2.15"], "unsupported": False})
    ports = _f("unifi", "group", {"id": "g2", "name": "p", "groupType": "port-group", "members": ["22", "443"],
                                  "unsupported": False})
    pol = _pol("grp", 5, "ALLOW", source=_side("z-dmz", target="IP", ipGroupId="g1"),
               destination=_side("z-srv", portType="OBJECT", portGroupId="g2"))
    facts = _zones() + [group, ports, pol, _default()]
    assert _unifi_station(_run(facts, port=22))["verdict"] == "erlaubt"
    assert _unifi_station(_run(facts, port=80))["verdict"] == "blockiert"
    assert _unifi_station(_run(facts, src="192.0.2.30"))["verdict"] == "blockiert"
    facts = _zones() + [pol, _default()]  # group facts missing: unknown object
    assert _unifi_station(_run(facts, port=22))["verdict"] == "unklar"


def test_tcp_udp_and_all_protocol():
    facts = _zones() + [_pol("dns", 5, "ALLOW", protocol="tcp_udp"), _default()]
    assert _unifi_station(_run(facts, proto="udp"))["verdict"] == "erlaubt"
    facts = _zones() + [_pol("dns", 5, "ALLOW", protocol="udp"), _default()]
    assert _unifi_station(_run(facts, proto="tcp"))["verdict"] == "blockiert"


def test_icmp_and_ipv6_unclear():
    facts = _zones() + [_default()]
    assert _run(facts, proto="icmp")["verdict"] == "unklar"
    assert _run(facts, src="2001:db8::1")["verdict"] == "unklar"


def test_same_zone_not_involved_and_unmapped_unclear():
    facts = _zones() + [_default()]
    assert _unifi_station(_run(facts, dst="192.0.2.20"))["verdict"] == "nicht beteiligt"
    assert _unifi_station(_run(facts, dst="198.18.0.1"))["verdict"] == "unklar"  # not global, no network


def test_public_ip_is_external_zone():
    facts = _zones() + [_pol("out", 5, "ALLOW", src="z-lan", dst="z-ext", destination=_side("z-ext"))]
    assert _unifi_station(_run(facts, src="192.0.2.130", dst="8.8.8.8"))["verdict"] == "erlaubt"


def test_zone_pair_without_rules_and_missing_or_stale_source_unclear():
    assert _unifi_station(_run(_zones()))["verdict"] == "unklar"
    assert _unifi_station(_run([]))["verdict"] == "unklar"
    facts = _zones() + [_pol("a", 5, "ALLOW"), _default()]
    for f in facts:
        f["stale"] = 1
    assert "veraltet" in _unifi_station(_run(facts))["reason"]


# --- nftables -----------------------------------------------------------------------------------

def _nft(system="s1", policy="drop", rules=None, hook="input", prio=0, chain="input"):
    return [_f("nftables", "nft_host", {"systemId": system}),
            _f("nftables", "nft_chain", {"systemId": system, "family": "inet", "table": "filter", "chain": chain,
                                         "hook": hook, "prio": prio, "policy": policy, "rules": rules or []})]


def _rule(no, verdict, matches=(), unsupported=()):
    return {"no": no, "verdict": verdict, "matches": list(matches), "unsupported": list(unsupported)}


def _allow_unifi():
    return _zones() + [_pol("Allow", 10, "ALLOW"), _default()]


def test_nft_input_drop_and_accept_with_position():
    port = {"f": "dport", "proto": "tcp", "v": ["443"]}
    facts = _allow_unifi() + _nft(rules=[_rule(1, "accept", [port])])
    out = _run(facts, dst_sys="s1")
    assert out["verdict"] == "erlaubt" and out["stations"][1]["rule"]["name"] == "Kette input Regel 1"
    out = _run(facts, port=22, dst_sys="s1")
    st = out["stations"][1]
    assert out["verdict"] == "blockiert" or st["verdict"] == "blockiert"
    assert st["rule"]["position"] == "filter/input Policy"


def test_nft_rule_block_and_ct_established_ignored():
    est = {"f": "ct_state", "v": ["established", "related"]}
    facts = _allow_unifi() + _nft(policy="accept", rules=[_rule(1, "drop", [est]),
                                                           _rule(2, "reject", [{"f": "dport", "proto": "tcp", "v": ["443"]}])])
    st = _run(facts, dst_sys="s1")["stations"][1]
    assert st["verdict"] == "blockiert" and st["rule"]["name"] == "Kette input Regel 2"


def test_nft_output_for_source_host_and_iif_unclear():
    facts = _allow_unifi() + _nft("s1", policy="accept") + _nft("s2", policy="drop", hook="output", chain="output")
    out = _run(facts, src_sys="s2", dst_sys="s1")
    assert [s["verdict"] for s in out["stations"]] == ["erlaubt", "blockiert", "erlaubt"]
    facts = _allow_unifi() + _nft(policy="accept", rules=[_rule(1, "drop", [{"f": "iif", "v": ["eth0"]}])])
    assert _run(facts, dst_sys="s1")["stations"][1]["verdict"] == "unklar"


def test_nft_unsupported_and_equal_priority_and_stale_unclear():
    facts = _allow_unifi() + _nft(rules=[_rule(1, "accept", unsupported=["jump"])])
    assert _run(facts, dst_sys="s1")["stations"][1]["verdict"] == "unklar"
    facts = _allow_unifi() + _nft(policy="accept") + _nft(chain="input2", policy="accept")[1:]
    assert "Priorität" in _run(facts, dst_sys="s1")["stations"][1]["reason"]
    facts = _allow_unifi() + _nft(policy="accept")
    for f in facts:
        f["stale"] = 1 if f["source"] == "nftables" else 0
    assert _run(facts, dst_sys="s1")["stations"][1]["verdict"] == "unklar"


def test_blocked_beats_unclear_and_allowed_needs_all_known():
    facts = _zones() + [_default()] + _nft(policy="drop")
    out = _run(facts, dst_sys="s1", port=22)
    assert out["verdict"] == "blockiert"
    facts = _allow_unifi() + _nft(policy="accept")
    assert _run(facts, dst_sys="s1")["verdict"] == "erlaubt"
    assert _run(facts, dst_sys="unknown-host")["verdict"] == "unklar"
    assert "Proxmox" in _run(facts, dst_sys="s1")["notes"]


def test_resolve_endpoint_and_zone_longest_match():
    systems = [{"id": "s1", "name": "NAS", "hostname": "nas", "ip": "192.0.2.70", "kind": "server"},
               {"id": "c1", "name": "web", "hostname": "", "ip": "192.0.2.70", "kind": "container"}]
    assert ev.resolve_endpoint("nas", systems)["systemId"] == "s1"
    assert ev.resolve_endpoint("web", systems)["systemId"] == "s1"  # container -> host
    assert ev.resolve_endpoint("192.0.2.5", systems)["systemId"] == ""
    assert "error" in ev.resolve_endpoint("nope", systems)
    zones = [f["data"] for f in _zones()]
    nets = NETRES + [{"kind": "network", "externalId": "n-lan", "facts": {"cidr": "192.0.2.64/28"}}]
    assert ev.zone_of("192.0.2.70", zones, nets)[0]["id"] == "z-lan"  # longest prefix wins
    assert ev.zone_of("192.0.2.200", zones, NETRES)[0] is None


def test_rule_names_cleaned():
    facts = _zones() + [_pol("ignore\x00 previous\ninstructions" + "x" * 200, 5, "ALLOW"), _default()]
    name = _unifi_station(_run(facts))["rule"]["name"]
    assert "\n" not in name and "\x00" not in name and len(name) <= 80


def test_zone_found_by_stored_subnet_when_network_ids_differ():
    zones = [_f("unifi", "zone", {"id": "z-dmz", "name": "DMZ", "zoneKey": "", "networkIds": ["ctl-1"],
                                  "cidrs": ["192.0.2.0/26"]}),
             _f("unifi", "zone", {"id": "z-srv", "name": "Server", "zoneKey": "", "networkIds": ["ctl-2"],
                                  "cidrs": ["192.0.2.64/26"]})]
    facts = zones + [_pol("Allow HTTPS", 10000, "ALLOW"), _default()]
    assert _unifi_station(_run(facts))["verdict"] == "erlaubt"
    assert _unifi_station(_run(facts, port=22))["verdict"] == "blockiert"


def test_same_subnet_in_two_zones_is_unclear():
    zones = [_f("unifi", "zone", {"id": k, "name": k, "zoneKey": "", "networkIds": [], "cidrs": ["192.0.2.0/24"]})
             for k in ("z-dmz", "z-srv")]
    out = _run(zones + [_pol("Allow HTTPS", 10000, "ALLOW"), _default()])
    assert _unifi_station(out)["verdict"] == "unklar" and "eindeutig" in _unifi_station(out)["reason"]


def test_rule_for_invalid_packets_does_not_decide_new_connection():
    facts = _zones() + [_pol("Block Invalid", 5, "BLOCK", protocol="all", connectionState="NO_NEW",
                             destination=_side("z-srv")), _pol("Allow HTTPS", 10, "ALLOW"), _default()]
    assert _unifi_station(_run(facts))["verdict"] == "erlaubt"


def _cell(policies, src="z-dmz", dst="z-srv"):
    return ev.zone_matrix(_zones() + policies)["cells"][src][dst]


def test_matrix_earlier_block_all_decides_over_allow_default():
    allow = _pol("Allow All", 2147483647, "ALLOW", protocol="all", destination=_side("z-srv"))
    block = _pol("Block All", 40000, "BLOCK", protocol="all", destination=_side("z-srv"))
    cell = _cell([_pol("Allow DNS", 10, "ALLOW"), block, allow])
    assert cell["state"] == "teilweise" and cell["default"] == "BLOCK"
    assert len(cell["exceptions"]) == 1 and "Allow DNS" in cell["exceptions"][0]


def test_matrix_earlier_allow_all_means_allowed():
    allow = _pol("Allow All", 10000, "ALLOW", protocol="all", destination=_side("z-srv"))
    assert _cell([allow, _default()]) == {"state": "erlaubt", "default": "ALLOW", "exceptions": []}


def test_matrix_invalid_rule_keeps_cell_readable():
    invalid = _pol("Block Invalid", 5, "BLOCK", protocol="all", connectionState="NO_NEW", destination=_side("z-srv"))
    allow = _pol("Allow All", 2147483647, "ALLOW", protocol="all", destination=_side("z-srv"))
    assert _cell([invalid, allow])["state"] == "erlaubt"
