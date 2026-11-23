from app import db


def test_missing_discovered_proxmox_row_is_kept_and_set_offline(temp_db):
    """A row for a guest that is no longer reported (e.g. a template now filtered out in
    proxmox_probe) is neither deleted nor otherwise changed by a scan -- only set offline."""
    system, _ = db.upsert_discovered_system({
        "discoveryKey": "proxmox:pve:vm:100", "kind": "vm", "name": "alte-vorlage",
        "status": "online", "discovered": 1, "discoverySource": "proxmox",
        "descriptionMd": "Notiz",
    })
    db.mark_systems_offline(set())
    after = db.get_system(system["id"])
    assert after is not None
    assert after["status"] == "offline"
    assert after["name"] == "alte-vorlage"
    assert after["descriptionMd"] == "Notiz"


def _discovered(key: str, source: str) -> dict:
    system, _ = db.upsert_discovered_system({
        "discoveryKey": key, "kind": "vm", "name": key, "status": "online",
        "discovered": 1, "discoverySource": source,
    })
    return system


def test_skipped_source_keeps_status(temp_db):
    system = _discovered("docker:a", "docker")
    db.mark_systems_offline(set(), {"docker"})
    assert db.get_system(system["id"])["status"] == "online"


def test_skipped_source_matches_token_in_mixed_value(temp_db):
    ki = _discovered("unifi:ki", "unifi+ki")
    arp = _discovered("unifi:arp", "unifi+arp")
    db.mark_systems_offline(set(), {"unifi"})
    assert db.get_system(ki["id"])["status"] == "online"
    assert db.get_system(arp["id"])["status"] == "online"


def test_unskipped_and_manual_rows_unchanged(temp_db):
    arp = _discovered("arp:a", "arp")
    manual = db.create_system({"kind": "server", "name": "manuell", "status": "online"})
    db.mark_systems_offline(set(), {"docker"})
    assert db.get_system(arp["id"])["status"] == "offline"
    assert db.get_system(manual["id"])["status"] == "online"


def test_empty_skip_sources_is_default_behaviour(temp_db):
    system = _discovered("docker:b", "docker")
    db.mark_systems_offline(set(), set())
    assert db.get_system(system["id"])["status"] == "offline"
