from app import pipeline


def test_tokens_lowercases_and_drops_short_words():
    assert pipeline._tokens("HP OfficeJet Pro 9010") == {"officejet", "pro", "9010"}


def test_match_printer_supplies_single_printer_gets_everything_unconditionally():
    # A single-printer household is the common case, and token matching has the most room to fail
    # when HA's own device name shares no words with the inventory entry at all.
    supplies = [{"name": "Unrelated HA Sensor Name", "percent": 50.0}]
    printers = [{"id": "p1", "name": "Buerodrucker", "vendor": "", "model": ""}]
    assert pipeline._match_printer_supplies(supplies, printers) == {"p1": supplies}


def test_match_printer_supplies_multiple_printers_uses_token_overlap():
    supplies = [
        {"name": "HP OfficeJet Pro 9010 Schwarz", "percent": 40.0},
        {"name": "Brother HL-L2350DW Toner", "percent": 10.0},
    ]
    printers = [
        {"id": "hp", "name": "HP OfficeJet Pro 9010", "vendor": "HP", "model": ""},
        {"id": "brother", "name": "Brother HL-L2350DW", "vendor": "Brother", "model": ""},
    ]
    result = pipeline._match_printer_supplies(supplies, printers)
    assert result["hp"] == [supplies[0]]
    assert result["brother"] == [supplies[1]]


def test_match_printer_supplies_unmatched_supply_is_dropped_not_misassigned():
    supplies = [{"name": "Completely Unrelated Name", "percent": 5.0}]
    printers = [
        {"id": "a", "name": "Canon Pixma", "vendor": "Canon", "model": ""},
        {"id": "b", "name": "Epson EcoTank", "vendor": "Epson", "model": ""},
    ]
    assert pipeline._match_printer_supplies(supplies, printers) == {}


def test_match_printer_supplies_no_printers_or_no_supplies_returns_empty():
    assert pipeline._match_printer_supplies([], [{"id": "a", "name": "x", "vendor": "", "model": ""}]) == {}
    assert pipeline._match_printer_supplies([{"name": "x", "percent": 1.0}], []) == {}


def test_link_omada_topology_resolves_uplink_mac_to_parent_id(temp_db):
    switch = temp_db.create_system({
        "kind": "network", "name": "Switch", "mac": "aa:aa:aa:aa:aa:01",
        "discoveryKey": "mac:aa:aa:aa:aa:aa:01",
    })
    ap = temp_db.create_system({
        "kind": "network", "name": "AP", "mac": "aa:aa:aa:aa:aa:02",
        "discoveryKey": "mac:aa:aa:aa:aa:aa:02",
        "extra": {"omada": {"uplinkMac": "aa:aa:aa:aa:aa:01"}},
    })
    unrelated = temp_db.create_system({
        "kind": "server", "name": "NAS", "mac": "aa:aa:aa:aa:aa:03",
        "discoveryKey": "mac:aa:aa:aa:aa:aa:03",
    })

    linked = pipeline._link_omada_topology()

    assert linked == 1
    assert temp_db.get_system(ap["id"])["parentId"] == switch["id"]
    assert temp_db.get_system(unrelated["id"])["parentId"] is None
    # Idempotent: running it again on an already-linked device must not count it a second time.
    assert pipeline._link_omada_topology() == 0


def test_assign_proxmox_parents_matches_guest_to_its_own_node(temp_db):
    pve1 = temp_db.create_system({"kind": "server", "name": "pve1", "hostname": "pve1"})
    pve2 = temp_db.create_system({"kind": "server", "name": "pve2", "hostname": "pve2"})
    guests = [
        {"name": "vm-on-1", "extra": {"proxmox": {"node": "pve1", "vmid": 100}}},
        {"name": "vm-on-2", "extra": {"proxmox": {"node": "pve2", "vmid": 200}}},
    ]

    pipeline._assign_proxmox_parents(guests, fallback_host_id="__fallback__")

    assert guests[0]["parentId"] == pve1["id"]
    assert guests[1]["parentId"] == pve2["id"]


def test_assign_proxmox_parents_falls_back_when_node_has_no_own_row(temp_db):
    # Single-node setup: the only row is whatever the credential is attached to, and every guest's
    # `node` is that same node -- there's nothing else in the inventory to match against.
    guests = [{"name": "vm", "extra": {"proxmox": {"node": "pve", "vmid": 100}}}]

    pipeline._assign_proxmox_parents(guests, fallback_host_id="host-1")

    assert guests[0]["parentId"] == "host-1"


def test_link_omada_topology_ignores_unresolvable_uplink(temp_db):
    orphan = temp_db.create_system({
        "kind": "network", "name": "Orphan AP", "mac": "bb:bb:bb:bb:bb:01",
        "discoveryKey": "mac:bb:bb:bb:bb:bb:01",
        "extra": {"omada": {"uplinkMac": "cc:cc:cc:cc:cc:99"}},  # no such device in the inventory
    })
    assert pipeline._link_omada_topology() == 0
    assert temp_db.get_system(orphan["id"])["parentId"] is None


def test_link_unifi_topology_resolves_controller_device_ids_instead_of_mac_addresses(temp_db):
    gateway = temp_db.create_system({
        "kind": "router", "name": "UCG Ultra", "mac": "aa:aa:aa:aa:aa:01",
        "extra": {"unifi": {"deviceId": "gateway"}},
    })
    switch = temp_db.create_system({
        "kind": "network", "name": "Switch", "mac": "aa:aa:aa:aa:aa:02",
        "extra": {"unifi": {"deviceId": "switch", "uplinkDeviceId": "gateway"}},
    })
    access_point = temp_db.create_system({
        "kind": "network", "name": "AP", "mac": "aa:aa:aa:aa:aa:03",
        "extra": {"unifi": {"deviceId": "ap", "uplinkDeviceId": "switch"}},
    })
    client = temp_db.create_system({
        "kind": "printer", "name": "Drucker", "mac": "aa:aa:aa:aa:aa:04",
        "extra": {"unifi": {"clientId": "client", "uplinkDeviceId": "ap"}},
    })

    linked = pipeline._link_unifi_topology()

    assert linked == 3
    assert temp_db.get_system(switch["id"])["parentId"] == gateway["id"]
    assert temp_db.get_system(access_point["id"])["parentId"] == switch["id"]
    assert temp_db.get_system(client["id"])["parentId"] == access_point["id"]
    assert pipeline._link_unifi_topology() == 0


def _unifi_pair(db):
    gw = db.create_system({"kind": "router", "name": "GW", "mac": "aa:aa:aa:aa:aa:01",
                           "extra": {"unifi": {"deviceId": "gateway"}}})
    sw = db.create_system({"kind": "network", "name": "SW", "mac": "aa:aa:aa:aa:aa:02",
                           "extra": {"unifi": {"deviceId": "sw", "uplinkDeviceId": "gateway"}}})
    return gw, sw


def test_manual_parent_survives_unifi_link(temp_db):
    gw, sw = _unifi_pair(temp_db)
    other = temp_db.create_system({"kind": "server", "name": "Other", "mac": "aa:aa:aa:aa:aa:09"})
    temp_db.update_system(sw["id"], {"parentId": other["id"], "extra": {**sw["extra"], "parentSource": "manual"}})
    assert pipeline._link_unifi_topology() == 0
    assert temp_db.get_system(sw["id"])["parentId"] == other["id"]


def test_manual_parent_survives_omada_link(temp_db):
    switch = temp_db.create_system({"kind": "network", "name": "Switch", "mac": "aa:aa:aa:aa:aa:01"})
    other = temp_db.create_system({"kind": "server", "name": "Other", "mac": "aa:aa:aa:aa:aa:09"})
    ap = temp_db.create_system({"kind": "network", "name": "AP", "mac": "aa:aa:aa:aa:aa:02",
                                "parentId": other["id"],
                                "extra": {"omada": {"uplinkMac": "aa:aa:aa:aa:aa:01"}, "parentSource": "manual"}})
    assert pipeline._link_omada_topology() == 0
    assert temp_db.get_system(ap["id"])["parentId"] == other["id"]
    assert switch["id"] != other["id"]


def test_controller_parent_is_updated_on_next_scan(temp_db):
    gw, sw = _unifi_pair(temp_db)
    assert pipeline._link_unifi_topology() == 1
    assert temp_db.get_system(sw["id"])["extra"]["parentSource"] == "unifi"
    gw2 = temp_db.create_system({"kind": "router", "name": "GW2", "mac": "aa:aa:aa:aa:aa:03",
                                 "extra": {"unifi": {"deviceId": "gateway2"}}})
    temp_db.update_system(sw["id"], {"extra": {**temp_db.get_system(sw["id"])["extra"],
                                               "unifi": {"deviceId": "sw", "uplinkDeviceId": "gateway2"}}})
    assert pipeline._link_unifi_topology() == 1
    assert temp_db.get_system(sw["id"])["parentId"] == gw2["id"]


def test_set_parent_from_source_keeps_manual_and_merges_extra(temp_db):
    a = temp_db.create_system({"kind": "server", "name": "A"})
    b = temp_db.create_system({"kind": "server", "name": "B"})
    vm = temp_db.create_system({"kind": "vm", "name": "VM", "extra": {"proxmox": {"node": "pve"}}})
    temp_db.set_parent_from_source(vm["id"], a["id"], "proxmox")
    got = temp_db.get_system(vm["id"])
    assert got["parentId"] == a["id"] and got["extra"] == {"proxmox": {"node": "pve"}, "parentSource": "proxmox"}
    temp_db.set_parent_from_source(vm["id"], b["id"], "proxmox")  # migrated VM follows
    assert temp_db.get_system(vm["id"])["parentId"] == b["id"]
    temp_db.update_system(vm["id"], {"extra": {**got["extra"], "parentSource": "manual"}})
    temp_db.set_parent_from_source(vm["id"], a["id"], "proxmox")
    assert temp_db.get_system(vm["id"])["parentId"] == b["id"]


def test_upsert_keeps_parent_source(temp_db):
    host = temp_db.create_system({"kind": "server", "name": "H"})
    vm, _ = temp_db.upsert_discovered_system({"kind": "vm", "name": "VM", "ip": "10.0.0.7",
                                              "discoveryKey": "proxmox:pve:vm:1",
                                              "extra": {"proxmox": {"node": "pve", "vmid": 1}}})
    temp_db.set_parent_from_source(vm["id"], host["id"], "proxmox")
    again, _ = temp_db.upsert_discovered_system({"kind": "vm", "name": "VM", "ip": "10.0.0.7",
                                                 "discoveryKey": "proxmox:pve:vm:1",
                                                 "extra": {"proxmox": {"node": "pve", "vmid": 1}}})
    assert temp_db.get_system(again["id"])["extra"]["parentSource"] == "proxmox"


def test_patch_parent_marks_manual_and_null_clears(temp_db):
    import asyncio
    from app.routes import systems as routes
    host = temp_db.create_system({"kind": "server", "name": "H"})
    dev = temp_db.create_system({"kind": "pc", "name": "D", "extra": {"k": 1}})

    def patch(**kw):
        return asyncio.run(routes.update_system(dev["id"], routes.SystemWrite(**kw), {}))["system"]

    s = patch(parentId=host["id"])
    assert s["extra"] == {"k": 1, "parentSource": "manual"}
    s = patch(notes="x")
    assert s["extra"]["parentSource"] == "manual"
    s = patch(parentId=None)
    assert s["parentId"] is None and "parentSource" not in s["extra"]
