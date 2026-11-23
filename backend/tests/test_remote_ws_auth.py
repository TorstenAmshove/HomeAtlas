"""The three WebSocket consoles (SSH, local Docker, remote Docker) through the real route: the gate
in `deps._ws_authenticate` (Origin, session, role, MFA) and the per-route target checks. A rejected
handshake is closed with 1008 *before* any counterpart (SSH/Docker) is opened -- asserted by making
every `open_*` fail the test. The gate itself is also covered in isolation by `test_auth_login.py`."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth, main, remote_admin, docker_admin
from remote_helpers import (isolate_crypto, make_container_system, make_session, make_ssh_system,
                            ws_headers)

PATHS = ("ssh-console", "docker-console", "remote-docker-console")


@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    isolate_crypto(monkeypatch, tmp_path)
    opened = []

    async def never(*a, **k):
        opened.append(a)
        raise AssertionError("counterpart must not be opened for a rejected handshake")

    monkeypatch.setattr(remote_admin, "open_ssh_pty", never)
    monkeypatch.setattr(remote_admin, "open_remote_docker_exec", never)
    monkeypatch.setattr(docker_admin, "open_exec_session", never)
    ssh_system, ssh_account = make_ssh_system()
    container = make_container_system()
    # remote-docker-console needs an SSH account on a system without a Proxmox account.
    return {"ssh_system": ssh_system, "ssh_account": ssh_account, "container": container,
            "token": make_session(), "opened": opened}


def _url(env, path: str) -> str:
    if path == "ssh-console":
        return f"/api/ws/systems/{env['ssh_system']['id']}/ssh-console?accountId={env['ssh_account']['id']}"
    if path == "docker-console":
        return f"/api/ws/systems/{env['container']['id']}/docker-console"
    return (f"/api/ws/systems/{env['ssh_system']['id']}/remote-docker-console"
            f"?accountId={env['ssh_account']['id']}&containerId=abc123")


def _refused(url: str, headers: dict) -> int:
    client = TestClient(main.app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url, headers=headers):
            pass
    return exc.value.code


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("origin", [None, "", "null", "http://evil.example", "http://evil.example:8280",
                                    "http://testserver.evil.example", "http://evilserver"],
                         ids=["missing", "empty", "null", "foreign", "foreign-port", "suffix", "substring"])
def test_ws_refused_for_bad_origin(env, path, origin):
    assert _refused(_url(env, path), ws_headers(env["token"], origin)) == 1008
    assert env["opened"] == []


@pytest.mark.parametrize("path", PATHS)
def test_ws_refused_without_host_header(env, path):
    headers = {**ws_headers(env["token"]), "host": ""}
    assert _refused(_url(env, path), headers) == 1008


@pytest.mark.parametrize("path", PATHS)
def test_ws_refused_without_or_with_bad_session(env, path):
    assert _refused(_url(env, path), ws_headers(None)) == 1008
    assert _refused(_url(env, path), ws_headers("not-a-session")) == 1008
    env_token = env["token"]
    auth.destroy_session(env_token)
    assert _refused(_url(env, path), ws_headers(env_token)) == 1008


@pytest.mark.parametrize("path", PATHS)
def test_ws_refused_for_member_and_unenrolled_admin(env, path):
    member = make_session(auth.ROLE_MEMBER)
    unenrolled = make_session(auth.ROLE_ADMIN, totp=False)
    assert _refused(_url(env, path), ws_headers(member)) == 1008
    assert _refused(_url(env, path), ws_headers(unenrolled)) == 1008
    assert env["opened"] == []


def test_ws_origin_port_is_ignored(env, monkeypatch):
    """Only hostnames are compared: nginx strips the port from Host, the browser's Origin keeps it.
    Proven by reaching the (faked) SSH open with a differing Origin port."""
    reached = []

    async def fake_open(host, account):
        reached.append(host)
        raise RuntimeError("stop here")

    monkeypatch.setattr(remote_admin, "open_ssh_pty", fake_open)
    client = TestClient(main.app)
    with client.websocket_connect(_url(env, "ssh-console"),
                                  headers=ws_headers(env["token"], "http://testserver:8280")) as ws:
        assert ws.receive_json()["type"] == "error"
    assert reached == ["10.0.0.5"]


@pytest.mark.parametrize("path", ["ssh-console", "remote-docker-console"])
def test_ws_ssh_target_checks(env, path):
    other_system, other_account = make_ssh_system(ip="10.0.0.6")
    token = env["token"]
    base = f"/api/ws/systems/{env['ssh_system']['id']}/{path}"
    extra = "&containerId=abc123" if path == "remote-docker-console" else ""
    headers = ws_headers(token)
    # account of another system
    assert _refused(f"{base}?accountId={other_account['id']}{extra}", headers) == 1008
    # unknown account / unknown system
    assert _refused(f"{base}?accountId=nope{extra}", headers) == 1008
    assert _refused(f"/api/ws/systems/nope/{path}?accountId={env['ssh_account']['id']}{extra}", headers) == 1008
    # no accountId at all
    assert _refused(f"{base}?{extra.lstrip('&')}", headers) == 1008
    # not an SSH-eligible account: wrong category, or a `login` account on the web port
    _, web = make_ssh_system(category="login", port=8443)
    from app import db
    db.update_account(web["id"], {"systemId": env["ssh_system"]["id"]})
    assert _refused(f"{base}?accountId={web['id']}{extra}", headers) == 1008
    _, token_acc = make_ssh_system(category="homeassistant")
    db.update_account(token_acc["id"], {"systemId": env["ssh_system"]["id"]})
    assert _refused(f"{base}?accountId={token_acc['id']}{extra}", headers) == 1008
    assert env["opened"] == []


@pytest.mark.parametrize("path", ["ssh-console", "remote-docker-console"])
def test_ws_ssh_target_without_address_is_refused(env, path):
    from app import db
    system = db.create_system({"name": "ohne", "kind": "server"})
    account = db.create_account({"systemId": system["id"], "category": "sshkey", "username": "root"})
    extra = "&containerId=abc123" if path == "remote-docker-console" else ""
    assert _refused(f"/api/ws/systems/{system['id']}/{path}?accountId={account['id']}{extra}",
                    ws_headers(env["token"])) == 1008


def test_remote_docker_console_requires_container_and_no_proxmox(env):
    from app import db
    headers = ws_headers(env["token"])
    base = f"/api/ws/systems/{env['ssh_system']['id']}/remote-docker-console?accountId={env['ssh_account']['id']}"
    assert _refused(base, headers) == 1008  # no containerId
    db.create_account({"systemId": env["ssh_system"]["id"], "category": "proxmox", "username": "t@pve!x"})
    assert _refused(base + "&containerId=abc123", headers) == 1008
    assert env["opened"] == []


def test_docker_console_target_checks(env):
    from app import db
    headers = ws_headers(env["token"])
    assert _refused("/api/ws/systems/nope/docker-console", headers) == 1008
    assert _refused(f"/api/ws/systems/{env['ssh_system']['id']}/docker-console", headers) == 1008  # not a container
    no_id = make_container_system(container_id=None)
    assert _refused(f"/api/ws/systems/{no_id['id']}/docker-console", headers) == 1008
    assert db.get_system(no_id["id"]) is not None
    assert env["opened"] == []
