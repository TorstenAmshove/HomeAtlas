from app import db


def _finding(name):
    return {"discoveryKey": "docker:immich:postgres", "kind": "container", "name": name,
            "ip": "192.168.1.20", "discovered": 1, "discoverySource": "docker", "extra": {}}


def test_unconfirmed_row_gets_new_name(temp_db):
    system, _ = db.upsert_discovered_system(_finding("Proxmox VM oder Container (20-31)"))
    db.upsert_discovered_system(_finding("postgres · immich"))
    assert db.get_system(system["id"])["name"] == "postgres · immich"


def test_confirmed_row_keeps_name(temp_db):
    system, _ = db.upsert_discovered_system(_finding("old"))
    db.update_system(system["id"], {"name": "Mein Postgres", "confirmed": 1})
    db.upsert_discovered_system(_finding("postgres · immich"))
    assert db.get_system(system["id"])["name"] == "Mein Postgres"
