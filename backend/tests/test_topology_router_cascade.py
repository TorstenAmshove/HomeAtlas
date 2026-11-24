"""Router cascade (FritzBox -> UniFi gateway -> its networks) in the physical and the Layer-3 plan.

The UniFi gateway's networks are controller resources owned by the system its account belongs to;
its WAN interface address (classic API, `db.set_wan_status`) sits in the FritzBox LAN and is what
chains it below the FritzBox.
"""
import re

from app import topology


def _box_y(svg: str, system_id: str) -> int:
    match = re.search(rf'data-system-id="{re.escape(system_id)}"[^>]*><rect x="[\d.-]+" y="(\d+)"', svg)
    assert match, f"{system_id} not drawn"
    return int(match.group(1))


def _cascade(db, ucg_ip: str = "", wan_ip: str = "192.168.178.2"):
    fritz = db.create_system({"kind": "router", "name": "FRITZ!Box", "ip": "192.168.178.1",
                              "discoveryKey": "k:fritz"})
    ucg = db.create_system({"kind": "router", "name": "UCG", "ip": ucg_ip, "discoveryKey": "k:ucg"})
    account = db.create_account({"systemId": ucg["id"], "label": "UCG", "category": "unifi"})
    resources = [
        {"source": "unifi", "ownerSystemId": ucg["id"], "siteExternalId": "default", "siteName": "Haus",
         "kind": "network", "externalId": f"net-{vlan}", "name": name,
         "facts": {"cidr": cidr, "vlanId": vlan}}
        for vlan, name, cidr in ((1, "Default", "192.168.1.0/24"), (20, "IoT", "192.168.20.0/24"))
    ] + [{"source": "unifi", "ownerSystemId": ucg["id"], "siteExternalId": "default", "siteName": "Haus",
          "kind": "wan", "externalId": "wan-1", "name": "Internet 1", "facts": {}}]
    db.sync_network_resources(account["id"], resources, [("default", "network"), ("default", "wan")])
    db.set_wan_status(account["id"], [{"name": "Internet 1", "type": "dhcp", "active": True,
                                       "ip": wan_ip, "interfaceIp": wan_ip}])
    for base, count in (("192.168.178", 3), ("192.168.1", 3), ("192.168.20", 3)):
        for host in range(count):
            db.create_system({"kind": "pc", "name": f"{base}-{host}", "ip": f"{base}.{50 + host}",
                              "discoveryKey": f"k:{base}.{host}"})
    return fritz, ucg


def test_wan_interface_address_chains_gateway_below_upstream_router(temp_db):
    fritz, ucg = _cascade(temp_db, ucg_ip="192.168.1.1")
    routers = [s for s in temp_db.list_systems() if s["kind"] == "router"]
    assert topology._router_parents(routers) == {fritz["id"]: None, ucg["id"]: fritz["id"]}


def test_layer3_shows_gateway_without_ip_below_fritzbox_with_vlan_labels(temp_db):
    fritz, ucg = _cascade(temp_db, ucg_ip="")
    svg = topology.render_layer3({})
    assert _box_y(svg, ucg["id"]) > _box_y(svg, fritz["id"])
    assert "VLAN 20" in svg and "192.168.20.0/24" in svg
    # the upstream LAN stays with the FritzBox and is not claimed by the gateway
    assert svg.count("192.168.178.0/24") == 1


def test_physical_plan_chains_router_cascade(temp_db):
    fritz, ucg = _cascade(temp_db, ucg_ip="192.168.1.1")
    svg = topology.render({})
    assert _box_y(svg, ucg["id"]) > _box_y(svg, fritz["id"])


def test_public_wan_address_does_not_chain(temp_db):
    fritz, ucg = _cascade(temp_db, ucg_ip="192.168.1.1", wan_ip="203.0.113.7")
    svg = topology.render({})
    assert _box_y(svg, ucg["id"]) == _box_y(svg, fritz["id"])


def test_router_without_any_subnet_is_never_an_upstream(temp_db):
    lonely = temp_db.create_system({"kind": "router", "name": "Alt", "discoveryKey": "k:alt"})
    fritz = temp_db.create_system({"kind": "router", "name": "FRITZ!Box", "ip": "192.168.178.1",
                                   "discoveryKey": "k:fritz"})
    routers = [s for s in temp_db.list_systems() if s["kind"] == "router"]
    assert topology._router_parents(routers) == {lonely["id"]: None, fritz["id"]: None}


def test_manual_router_parent_still_wins(temp_db):
    fritz, ucg = _cascade(temp_db, ucg_ip="192.168.1.1", wan_ip="203.0.113.7")  # nothing to infer from
    temp_db.update_system(ucg["id"], {"parentId": fritz["id"]})
    routers = [s for s in temp_db.list_systems() if s["kind"] == "router"]
    assert topology._router_parents(routers)[ucg["id"]] == fritz["id"]
    svg = topology.render({})
    assert _box_y(svg, ucg["id"]) > _box_y(svg, fritz["id"])


def _merged_gateway(db, wan_alias: str = "192.168.178.20"):
    """UCG as seen in a real cascade: its LAN address as primary IP and its WAN address in the
    FritzBox LAN as a further address (a second scan row merged into it), no classic-API WAN data."""
    fritz = db.create_system({"kind": "router", "name": "FRITZ!Box", "ip": "192.168.178.1",
                              "discoveryKey": "k:fritz"})
    ucg = db.create_system({"kind": "router", "name": "UCG", "ip": "192.168.42.2",
                            "mac": "9e:05:d6:aa:d2:9d", "discoveryKey": "mac:9e:05:d6:aa:d2:9d"})
    wan_row = db.create_system({"kind": "other", "name": "UCG WAN", "ip": wan_alias,
                                "mac": "9c:05:d6:aa:d2:9c", "discoveryKey": "mac:9c:05:d6:aa:d2:9c"})
    db.merge_systems(ucg["id"], wan_row["id"])
    account = db.create_account({"systemId": ucg["id"], "label": "UCG", "category": "unifi"})
    db.sync_network_resources(account["id"], [
        {"source": "unifi", "ownerSystemId": ucg["id"], "siteExternalId": "default", "siteName": "Haus",
         "kind": "network", "externalId": f"net-{vlan}", "name": f"Netz {vlan}",
         "facts": {"cidr": f"192.168.{vlan}.0/24", "vlanId": vlan}}
        for vlan in (22, 23, 40, 42, 100)
    ], [("default", "network")])
    return fritz, ucg


def test_further_address_in_upstream_lan_chains_gateway(temp_db):
    fritz, ucg = _merged_gateway(temp_db)
    assert {a["ip"] for a in temp_db.list_aliases(ucg["id"])} == {"192.168.178.20"}
    routers = [s for s in temp_db.list_systems() if s["kind"] == "router"]
    assert topology._router_parents(routers) == {fritz["id"]: None, ucg["id"]: fritz["id"]}
    assert _box_y(topology.render({}), ucg["id"]) > _box_y(topology.render({}), fritz["id"])
    assert _box_y(topology.render_layer3({}), ucg["id"]) > _box_y(topology.render_layer3({}), fritz["id"])


def test_public_further_address_does_not_chain(temp_db):
    fritz, ucg = _merged_gateway(temp_db, wan_alias="203.0.113.7")
    routers = [s for s in temp_db.list_systems() if s["kind"] == "router"]
    assert topology._router_parents(routers)[ucg["id"]] is None
