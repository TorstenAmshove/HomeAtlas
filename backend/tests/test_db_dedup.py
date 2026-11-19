"""Tests for the db package's cross-scheme dedup fallbacks (find_system_by_mac / find_system_by_proxmox /
find_system_by_ip_and_hostname / find_system_for_merge) and their integration into
upsert_discovered_system. Without these, a device found under one discoveryKey scheme by one
source (e.g. a network sweep that never resolved a MAC) and under a different scheme by another
(e.g. Proxmox, keyed by MAC) would silently duplicate instead of merging into the existing row."""
from app import db


def test_find_system_by_mac_matches_and_ignores_empty(temp_db):
    system = temp_db.create_system({"kind": "server", "name": "Host", "mac": "aa:bb:cc:dd:ee:ff"})
    assert temp_db.find_system_by_mac("aa:bb:cc:dd:ee:ff")["id"] == system["id"]
    assert temp_db.find_system_by_mac("AA:BB:CC:DD:EE:FF")["id"] == system["id"]  # case-insensitive
    assert temp_db.find_system_by_mac("") is None
    assert temp_db.find_system_by_mac("11:22:33:44:55:66") is None


def test_find_system_by_proxmox_matches_node_and_vmid_exactly(temp_db):
    vm = temp_db.create_system({
        "kind": "vm", "name": "VM101", "extra": {"proxmox": {"node": "pve", "vmid": 101}},
    })
    temp_db.create_system({
        "kind": "vm", "name": "VM102", "extra": {"proxmox": {"node": "pve", "vmid": 102}},
    })
    assert temp_db.find_system_by_proxmox("pve", 101)["id"] == vm["id"]
    assert temp_db.find_system_by_proxmox("pve", 999) is None
    assert temp_db.find_system_by_proxmox("other-node", 101) is None
    assert temp_db.find_system_by_proxmox("", 101) is None
    assert temp_db.find_system_by_proxmox("pve", None) is None


def test_find_system_by_ip_and_hostname_requires_both(temp_db):
    system = temp_db.create_system({
        "kind": "pc", "name": "Laptop", "ip": "10.0.0.20", "hostname": "laptop.local",
    })
    assert temp_db.find_system_by_ip_and_hostname("10.0.0.20", "laptop.local")["id"] == system["id"]
    assert temp_db.find_system_by_ip_and_hostname("10.0.0.20", "other.local") is None
    assert temp_db.find_system_by_ip_and_hostname("10.0.0.99", "laptop.local") is None
    assert temp_db.find_system_by_ip_and_hostname("", "laptop.local") is None


def test_find_system_for_merge_prefers_mac_over_proxmox_over_ip_hostname(temp_db):
    by_mac = temp_db.create_system({"kind": "vm", "name": "ByMac", "mac": "aa:aa:aa:aa:aa:aa"})
    temp_db.create_system({
        "kind": "vm", "name": "ByProxmox", "extra": {"proxmox": {"node": "pve", "vmid": 1}},
    })
    # A finding that could match either the MAC row or the Proxmox row must resolve to MAC, since
    # that is the strongest/most trustworthy identity of the three.
    found = {"mac": "aa:aa:aa:aa:aa:aa", "extra": {"proxmox": {"node": "pve", "vmid": 1}}}
    assert temp_db.find_system_for_merge(found)["id"] == by_mac["id"]


def test_upsert_merges_proxmox_guest_whose_key_scheme_flipped_to_mac(temp_db):
    """The concrete bug: proxmox_probe.probe's discoveryKey is `proxmox:<node>:<kind>:<vmid>` when
    net0 has no parseable MAC, and `mac:<mac>` once it does -- the same guest, same vmid, flips
    between the two across scans. Without find_system_for_merge, the second scan's exact-key
    lookup misses and the guest duplicates instead of updating."""
    first_scan = {
        "discoveryKey": "proxmox:pve:vm:101", "kind": "vm", "name": "nextcloud",
        "mac": "", "ip": "", "extra": {"proxmox": {"node": "pve", "vmid": 101}},
    }
    system, created = db.upsert_discovered_system(first_scan)
    assert created

    second_scan = {
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "kind": "vm", "name": "nextcloud",
        "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50",
        "extra": {"proxmox": {"node": "pve", "vmid": 101}},
    }
    merged, created_again = db.upsert_discovered_system(second_scan)

    assert not created_again
    assert merged["id"] == system["id"]
    assert merged["mac"] == "aa:bb:cc:dd:ee:ff"
    assert merged["discoveryKey"] == "mac:aa:bb:cc:dd:ee:ff"
    assert len(db.list_systems()) == 1  # no duplicate row


def test_upsert_merges_device_found_by_ip_only_then_by_mac_via_ip_hostname_match(temp_db):
    """A hand-created (confirmed) entry with just an address and hostname, later re-discovered by
    a network scan that resolves a MAC (e.g. a phone's privacy MAC rotated, so it's a "new" MAC
    the discoveryKey scheme has never seen for this device) -- ip+hostname is the only identity
    that still lines up."""
    hand_created = db.create_system({
        "kind": "mobile", "name": "Handy", "ip": "10.0.0.40", "hostname": "handy.local",
        "confirmed": 1, "discoveryKey": "",
    })

    rediscovered = {
        "discoveryKey": "mac:11:22:33:44:55:66", "kind": "mobile", "name": "Handy",
        "mac": "11:22:33:44:55:66", "ip": "10.0.0.40", "hostname": "handy.local",
    }
    merged, created = db.upsert_discovered_system(rediscovered)

    assert not created
    assert merged["id"] == hand_created["id"]
    assert merged["mac"] == "11:22:33:44:55:66"
    assert len(db.list_systems()) == 1


def test_upsert_does_not_merge_unrelated_devices(temp_db):
    db.create_system({"kind": "pc", "name": "PC1", "ip": "10.0.0.1", "hostname": "pc1"})
    finding = {
        "discoveryKey": "mac:99:99:99:99:99:99", "kind": "pc", "name": "PC2",
        "mac": "99:99:99:99:99:99", "ip": "10.0.0.2", "hostname": "pc2",
    }
    _, created = db.upsert_discovered_system(finding)
    assert created
    assert len(db.list_systems()) == 2


def test_upsert_keeps_unifi_name_over_other_discovery_sources(temp_db):
    system, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "scanner-host", "mac": "aa:bb:cc:dd:ee:ff",
    })
    unifi, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "Kuechendrucker", "mac": "aa:bb:cc:dd:ee:ff",
        "extra": {"unifi": {"name": "Kuechendrucker"}},
    })
    later, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "printer.local", "mac": "aa:bb:cc:dd:ee:ff",
    })

    assert unifi["id"] == system["id"]
    assert later["name"] == "Kuechendrucker"


def test_upsert_updates_unifi_name_but_preserves_confirmed_homeatlas_name(temp_db):
    system, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "Alter UniFi-Name", "mac": "aa:bb:cc:dd:ee:ff",
        "extra": {"unifi": {"name": "Alter UniFi-Name"}},
    })
    renamed, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "Neuer UniFi-Name", "mac": "aa:bb:cc:dd:ee:ff",
        "extra": {"unifi": {"name": "Neuer UniFi-Name"}},
    })
    temp_db.update_system(system["id"], {"name": "HomeAtlas-Name", "confirmed": 1})
    confirmed, _ = db.upsert_discovered_system({
        "discoveryKey": "mac:aa:bb:cc:dd:ee:ff", "name": "Noch ein UniFi-Name", "mac": "aa:bb:cc:dd:ee:ff",
        "extra": {"unifi": {"name": "Noch ein UniFi-Name"}},
    })

    assert renamed["name"] == "Neuer UniFi-Name"
    assert confirmed["name"] == "HomeAtlas-Name"


# --- find_system_by_unique_controller_ip: routed devices seen by IP only ------------------------

def _unifi_finding(ip="10.20.0.5", mac="aa:bb:cc:00:00:01", name="UniFi-Name"):
    return {
        "discoveryKey": f"mac:{mac}", "kind": "pc", "name": name, "mac": mac, "ip": ip,
        "discoverySource": "unifi+ki", "extra": {"unifi": {"name": name}},
    }


def _scan_finding(ip="10.20.0.5"):
    return {"discoveryKey": f"ip:{ip}", "kind": "other", "name": f"Gerät {ip}", "ip": ip,
            "discoverySource": "ping", "extra": {}}


def test_merge_ip_only_found_into_single_controller_row(temp_db):
    row = temp_db.create_system(_unifi_finding())
    system, created = temp_db.upsert_discovered_system(_scan_finding())
    assert not created
    assert system["id"] == row["id"]
    assert len(temp_db.list_systems()) == 1


def test_merge_controller_found_into_existing_ip_only_scan_row(temp_db):
    """Pipeline order: network scan first (no MAC off-segment), controller second."""
    scan_row, _ = temp_db.upsert_discovered_system(_scan_finding())
    system, created = temp_db.upsert_discovered_system(_unifi_finding())
    assert not created
    assert system["id"] == scan_row["id"]
    assert system["mac"] == "aa:bb:cc:00:00:01"
    # a second identical run must neither duplicate nor flip the discoveryKey
    for _ in range(2):
        again, created = temp_db.upsert_discovered_system(_scan_finding())
        assert not created and again["id"] == scan_row["id"]
        again, created = temp_db.upsert_discovered_system(_unifi_finding())
        assert not created and again["id"] == scan_row["id"]
    assert len(temp_db.list_systems()) == 1
    assert temp_db.get_system(scan_row["id"])["discoveryKey"] == "mac:aa:bb:cc:00:00:01"


def test_no_merge_when_two_rows_share_ip(temp_db):
    temp_db.create_system(_unifi_finding(mac="aa:bb:cc:00:00:01"))
    temp_db.create_system(_unifi_finding(mac="aa:bb:cc:00:00:02"))
    assert temp_db.find_system_by_unique_controller_ip(_scan_finding()) is None
    _, created = temp_db.upsert_discovered_system(_scan_finding())
    assert created


def test_no_merge_when_no_controller_origin(temp_db):
    temp_db.create_system({"discoveryKey": "mac:aa:bb:cc:00:00:09", "name": "X", "mac": "aa:bb:cc:00:00:09",
                           "ip": "10.20.0.5", "discoverySource": "ping+mdns", "extra": {}})
    assert temp_db.find_system_by_unique_controller_ip(_scan_finding()) is None
    assert temp_db.find_system_by_unique_controller_ip({"ip": "10.20.0.5", "mac": "aa:bb:cc:00:00:10"}) is None


def test_no_merge_when_macs_conflict(temp_db):
    temp_db.create_system(_unifi_finding(mac="aa:bb:cc:00:00:01"))
    other = {"discoveryKey": "mac:aa:bb:cc:00:00:02", "ip": "10.20.0.5", "mac": "aa:bb:cc:00:00:02",
             "extra": {"unifi": {}}}
    assert temp_db.find_system_by_unique_controller_ip(other) is None


def test_no_merge_on_empty_ip(temp_db):
    temp_db.create_system({"name": "A", "ip": "", "extra": {"unifi": {}}})
    assert temp_db.find_system_by_unique_controller_ip({"ip": "", "extra": {"unifi": {}}}) is None


def test_ip_hostname_rule_still_wins(temp_db):
    temp_db.create_system(_unifi_finding(ip="10.20.0.7", mac="aa:bb:cc:00:00:07"))
    by_host = temp_db.create_system({"name": "Laptop", "ip": "10.20.0.8", "hostname": "laptop.local"})
    found = {"ip": "10.20.0.8", "hostname": "laptop.local", "extra": {"unifi": {}}}
    assert temp_db.find_system_for_merge(found)["id"] == by_host["id"]


def test_ip_merge_keeps_confirmed_manual_fields(temp_db):
    row = temp_db.create_system({
        "discoveryKey": "ip:10.20.0.5", "name": "Mein Drucker", "location": "Büro",
        "descriptionMd": "Handgeschrieben", "kind": "printer", "importance": "high",
        "ip": "10.20.0.5", "confirmed": 1, "discovered": 1,
    })
    system, created = temp_db.upsert_discovered_system(_unifi_finding(name="UniFi-Name"))
    assert not created and system["id"] == row["id"]
    assert system["name"] == "Mein Drucker"
    assert system["location"] == "Büro"
    assert system["descriptionMd"] == "Handgeschrieben"
    assert system["kind"] == "printer"
    assert system["importance"] == "high"
    assert system["mac"] == "aa:bb:cc:00:00:01"  # empty field filled


def test_ip_merge_unconfirmed_takes_unifi_name(temp_db):
    scan_row, _ = temp_db.upsert_discovered_system(_scan_finding())
    system, _ = temp_db.upsert_discovered_system(_unifi_finding(name="UniFi-Name"))
    assert system["id"] == scan_row["id"] and system["name"] == "UniFi-Name"
