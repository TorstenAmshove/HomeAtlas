"""init_db migrates the retired `router` account category to `login` (issue #134)."""
from app import db


def test_init_db_migrates_router_accounts_to_login(temp_db):
    system = db.create_system({"kind": "router", "name": "R", "ip": "10.0.0.1"})
    ids = {}
    for category in ("router", "login", "sshkey"):
        ids[category] = db.create_account(
            {"systemId": system["id"], "label": category, "category": category})["id"]

    db.init_db()
    db.init_db()

    assert db.get_account(ids["router"])["category"] == "login"
    assert db.get_account(ids["login"])["category"] == "login"
    assert db.get_account(ids["sshkey"])["category"] == "sshkey"
