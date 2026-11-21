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
