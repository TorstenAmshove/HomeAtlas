"""A MAC address is an identifier, not a name: UniFi reports it as `name` for clients without an
alias, and that must never displace a real name from another source."""
from app import db, prompts, unifi_probe

MAC = "bc:24:11:04:c8:03"
KEY = f"mac:{MAC}"
SITE = {"id": "s", "name": "Zuhause"}


def _unifi(name):
    client = {"id": "c", "type": "WIRED", "macAddress": MAC, "ipAddress": "192.168.40.10", "name": name}
    return unifi_probe._client_system(SITE, client)


def _proxmox(name="flatcar-dmz"):
    return {"discoveryKey": KEY, "mac": MAC, "ip": "192.168.40.10", "kind": "vm", "name": name,
            "discoverySource": "proxmox", "extra": {"proxmox": {"node": "pve", "vmid": 100}}}


def test_unifi_client_without_alias_has_no_assigned_name():
    finding = _unifi(MAC.upper().replace(":", "-"))
    assert finding["extra"]["unifi"]["name"] == ""
    assert finding["name"] != MAC
    assert "192" not in finding["name"]


def test_mac_from_unifi_does_not_displace_proxmox_name(temp_db):
    db.upsert_discovered_system(_proxmox())
    after_unifi, _ = db.upsert_discovered_system(_unifi(MAC))
    assert after_unifi["name"] == "flatcar-dmz"
    after_proxmox, _ = db.upsert_discovered_system(_proxmox())
    assert after_proxmox["name"] == "flatcar-dmz"


def test_stored_mac_name_heals_on_next_scan(temp_db):
    db.create_system({"discoveryKey": KEY, "mac": MAC, "name": MAC, "kind": "vm", "discovered": 1,
                      "extra": {"unifi": {"name": MAC}, "aiConfidence": "high"}})
    db.upsert_discovered_system(_unifi(MAC))
    healed, _ = db.upsert_discovered_system(_proxmox())
    assert healed["name"] == "flatcar-dmz"


def test_nameless_unifi_finding_keeps_existing_name(temp_db):
    db.upsert_discovered_system({"discoveryKey": KEY, "mac": MAC, "name": "drucker"})
    system, _ = db.upsert_discovered_system(_unifi(""))
    assert system["name"] == "drucker"


def test_real_unifi_alias_still_wins(temp_db):
    db.upsert_discovered_system(_proxmox())
    db.upsert_discovered_system(_unifi("Reverse Proxy"))
    system, _ = db.upsert_discovered_system(_proxmox())
    assert system["name"] == "Reverse Proxy"


def test_confirmed_name_is_untouched(temp_db):
    db.create_system({"discoveryKey": KEY, "mac": MAC, "name": "Mein Proxy", "confirmed": 1})
    system, _ = db.upsert_discovered_system(_unifi(MAC))
    assert system["name"] == "Mein Proxy"


def test_classify_prompt_separates_guest_nic_from_host():
    assert "virtuelle Netzwerkkarte" in prompts.CLASSIFY_SYSTEM
