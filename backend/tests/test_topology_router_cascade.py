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
