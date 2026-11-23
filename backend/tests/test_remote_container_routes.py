"""REST routes for local Docker containers (`/container/{action}`, `/container/logs`): role gate
(ADMIN vs. MEMBER, real `require_admin`), target checks, result mapping and the access log.
`docker_admin` itself is covered by test_docker_admin.py."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, docker_admin, main
from app.routes import remote
from remote_helpers import access_actions, make_container_system


class _Calls(list):
    outcome: dict


def _client(role: str) -> TestClient:
    user = {"id": "u1", "role": role, "username": role.lower(), "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    return TestClient(main.app)


@pytest.fixture()
def admin(temp_db):
    try:
        yield _client(auth.ROLE_ADMIN)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def member(temp_db):
    try:
        yield _client(auth.ROLE_MEMBER)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def docker(monkeypatch):
    calls = _Calls()
    outcome = {"ok": True, "error": ""}

    def make(name):
        async def fake(container_id):
            calls.append((name, container_id))
            return dict(outcome)
        return fake

    monkeypatch.setattr(remote, "_CONTAINER_ACTIONS", {n: make(n) for n in ("start", "stop", "restart")})
    calls.outcome = outcome
    return calls


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_admin_can_control_container(admin, docker, action):
    system = make_container_system()
    resp = admin.post(f"/api/systems/{system['id']}/container/{action}")
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    assert docker == [(action, "abc123")]
    assert f"container.{action}" in access_actions()


def test_member_is_refused_without_touching_docker(member, docker):
    system = make_container_system()
    assert member.post(f"/api/systems/{system['id']}/container/restart").status_code == 403
    assert member.get(f"/api/systems/{system['id']}/container/logs").status_code == 403
    assert docker == []
    assert "container.restart" not in access_actions()


def test_unauthenticated_is_refused(temp_db, docker):
    system = make_container_system()
    client = TestClient(main.app)
    assert client.post(f"/api/systems/{system['id']}/container/stop").status_code == 401
    assert docker == []


def test_unknown_action_unknown_system_wrong_kind_and_missing_id(admin, docker):
    system = make_container_system()
    assert admin.post(f"/api/systems/{system['id']}/container/delete").status_code == 404
    assert admin.post("/api/systems/nope/container/start").status_code == 404
    server = db.create_system({"name": "nas", "kind": "nas", "ip": "10.0.0.2",
                               "extra": {"docker": {"containerId": "zzz"}}})
    assert admin.post(f"/api/systems/{server['id']}/container/start").status_code == 404
    no_id = make_container_system(container_id=None)
    assert admin.post(f"/api/systems/{no_id['id']}/container/start").status_code == 400
    assert docker == []


def test_docker_error_becomes_400_and_is_logged_as_failed(admin, docker):
    docker.outcome.update(ok=False, error="No such container")
    system = make_container_system()
    resp = admin.post(f"/api/systems/{system['id']}/container/start")
    assert resp.status_code == 400 and resp.json()["detail"] == "No such container"
    entry = next(e for e in db.list_access_log(10) if e["action"] == "container.start")
    assert not entry["ok"]


def test_container_logs_stream_for_admin(admin, monkeypatch):
    seen = {}

    async def fake_logs(container_id, tail):
        seen["args"] = (container_id, tail)
        yield b"line 1\n"
        yield b"line 2\n"

    monkeypatch.setattr(docker_admin, "stream_logs", fake_logs)
    system = make_container_system()
    resp = admin.get(f"/api/systems/{system['id']}/container/logs?tail=5")
    assert resp.status_code == 200 and resp.text == "line 1\nline 2\n"
    assert seen["args"] == ("abc123", 5)


def test_container_logs_rejections(admin, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not stream")
        yield b""

    monkeypatch.setattr(docker_admin, "stream_logs", boom)
    assert admin.get("/api/systems/nope/container/logs").status_code == 404
    other = db.create_system({"name": "nas", "kind": "nas", "ip": "10.0.0.2"})
    assert admin.get(f"/api/systems/{other['id']}/container/logs").status_code == 404
    no_id = make_container_system(container_id=None)
    assert admin.get(f"/api/systems/{no_id['id']}/container/logs").status_code == 400
