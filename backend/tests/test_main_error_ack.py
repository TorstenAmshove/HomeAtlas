import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def _system_with_events(n=2):
    s = db.create_system({"name": "A", "ip": "10.0.0.1"})
    return s, [db.add_device_error_event(s["id"], "error", f"e{i}") for i in range(n)]


def test_acknowledge_requires_admin(temp_db):
    s, evs = _system_with_events()
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        c = TestClient(main.app)
        assert c.post(f"/api/systems/{s['id']}/errors/acknowledge").status_code == 403
        assert c.post(f"/api/systems/{s['id']}/errors/{evs[0]['id']}/acknowledge").status_code == 403
    finally:
        main.app.dependency_overrides.clear()
    assert db.count_error_events_by_system()[s["id"]]["error"] == 2


def test_acknowledge_one_unknown_system_or_event_is_404(client):
    s, _ = _system_with_events()
    assert client.post("/api/systems/nope/errors/x/acknowledge").status_code == 404
    assert client.post(f"/api/systems/{s['id']}/errors/nope/acknowledge").status_code == 404
    assert client.post("/api/systems/nope/errors/acknowledge").status_code == 404


def test_event_of_other_system_is_404_and_untouched(client):
    s, _ = _system_with_events()
    other, oevs = _system_with_events(1)
    assert client.post(f"/api/systems/{s['id']}/errors/{oevs[0]['id']}/acknowledge").status_code == 404
    assert db.count_error_events_by_system()[other["id"]]["error"] == 1


def test_acknowledge_all_returns_count_and_zero_is_200(client):
    s, _ = _system_with_events()
    assert client.post(f"/api/systems/{s['id']}/errors/acknowledge").json() == {"acknowledged": 2}
    r = client.post(f"/api/systems/{s['id']}/errors/acknowledge")
    assert r.status_code == 200 and r.json() == {"acknowledged": 0}


def test_acknowledge_twice_is_200_and_keeps_timestamp(client):
    s, evs = _system_with_events()
    url = f"/api/systems/{s['id']}/errors/{evs[0]['id']}/acknowledge"
    assert client.post(url).json() == {"ok": True}
    first = {e["id"]: e for e in client.get(f"/api/systems/{s['id']}/errors").json()["events"]}[evs[0]["id"]]
    assert client.post(url).status_code == 200
    again = {e["id"]: e for e in client.get(f"/api/systems/{s['id']}/errors").json()["events"]}[evs[0]["id"]]
    assert first["acknowledgedAt"] and first["acknowledgedAt"] == again["acknowledgedAt"]


def test_systems_list_error_count_only_unacknowledged(client):
    s, evs = _system_with_events()
    client.post(f"/api/systems/{s['id']}/errors/{evs[0]['id']}/acknowledge")
    row = next(x for x in client.get("/api/systems").json()["systems"] if x["id"] == s["id"])
    assert row["errorCount"] == 1


def test_systems_list_splits_errors_and_warnings(client):
    s, _ = _system_with_events(1)
    db.add_device_error_event(s["id"], "warning", "w1")
    only_warn = db.create_system({"name": "B", "ip": "10.0.0.2"})
    for i in range(3):
        db.add_device_error_event(only_warn["id"], "warning", f"w{i}")
    clean = db.create_system({"name": "C", "ip": "10.0.0.3"})
    rows = {x["id"]: x for x in client.get("/api/systems").json()["systems"]}
    assert (rows[s["id"]]["errorCount"], rows[s["id"]]["warningCount"]) == (1, 1)
    assert (rows[only_warn["id"]]["errorCount"], rows[only_warn["id"]]["warningCount"]) == (0, 3)
    assert (rows[clean["id"]]["errorCount"], rows[clean["id"]]["warningCount"]) == (0, 0)
    client.post(f"/api/systems/{only_warn['id']}/errors/acknowledge")
    row = next(x for x in client.get("/api/systems").json()["systems"] if x["id"] == only_warn["id"])
    assert row["warningCount"] == 0
