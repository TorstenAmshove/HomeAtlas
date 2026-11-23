"""The three WebSocket consoles through the real route with fake counterparts: bytes both ways,
resize, `exit` on EOF, cleanup, access log, and the failure path (error frame, close 1011,
`ok=False`). `_relay_terminal` itself is covered in isolation by test_remote_terminal_relay.py and
test_relay_terminal_exit.py."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import docker_admin, main, remote_admin
from remote_helpers import (access_actions, isolate_crypto, make_container_system, make_session,
                            make_ssh_system, ws_headers)
from app import db


class _Stdin:
    def __init__(self, sink):
        self.sink = sink

    def write(self, data):
        self.sink.append(data)


class _Stdout:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def read(self, n):
        if self.chunks:
            item = self.chunks.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.sleep(3600)


class FakeProcess:
    """asyncssh-shaped: stdout.read, stdin.write, change_terminal_size, close."""

    def __init__(self, chunks=(), eof=False):
        self.written, self.sizes, self.closed = [], [], False
        self.stdin = _Stdin(self.written)
        self.stdout = _Stdout(list(chunks) + ([b""] if eof else []))

    def change_terminal_size(self, cols, rows):
        self.sizes.append((cols, rows))

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeExec(FakeProcess):
    """docker_admin.ExecSession-shaped: read/write/resize/close."""

    async def read(self, n=4096):
        return await self.stdout.read(n)

    def write(self, data):
        self.written.append(data)

    async def resize(self, cols, rows):
        self.sizes.append((cols, rows))


@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    isolate_crypto(monkeypatch, tmp_path)
    system, account = make_ssh_system()
    container = make_container_system()
    token = make_session()
    return {"headers": ws_headers(token), "system": system, "account": account, "container": container,
            "monkeypatch": monkeypatch}


def _targets(env):
    ssh = f"/api/ws/systems/{env['system']['id']}/ssh-console?accountId={env['account']['id']}"
    rdocker = (f"/api/ws/systems/{env['system']['id']}/remote-docker-console"
               f"?accountId={env['account']['id']}&containerId=abc123")
    local = f"/api/ws/systems/{env['container']['id']}/docker-console"
    return {"ssh": ssh, "remote-docker": rdocker, "docker": local}


def _install(env, kind, process, connection=None):
    mp = env["monkeypatch"]
    seen = {}
    if kind == "ssh":
        async def open_ssh(host, account):
            seen["args"] = (host, account["id"])
            return connection, process
        mp.setattr(remote_admin, "open_ssh_pty", open_ssh)
    elif kind == "remote-docker":
        async def open_rd(host, account, container_id):
            seen["args"] = (host, account["id"], container_id)
            return connection, process
        mp.setattr(remote_admin, "open_remote_docker_exec", open_rd)
    else:
        async def open_local(container_id):
            seen["args"] = (container_id,)
            return process
        mp.setattr(docker_admin, "open_exec_session", open_local)
    return seen


KINDS = ["ssh", "remote-docker", "docker"]


def _new_process(kind, **kw):
    return (FakeExec if kind == "docker" else FakeProcess)(**kw)


@pytest.mark.parametrize("kind", KINDS)
def test_console_relays_both_ways_and_cleans_up(env, kind):
    process, connection = _new_process(kind, chunks=[b"$ "]), FakeConnection()
    seen = _install(env, kind, process, connection)
    client = TestClient(main.app)
    with client.websocket_connect(_targets(env)[kind], headers=env["headers"]) as ws:
        assert ws.receive_bytes() == b"$ "
        ws.send_bytes(b"ls\n")
        ws.send_json({"type": "resize", "cols": 100, "rows": 30})
        ws.send_json({"type": "resize", "cols": "x"})  # invalid: ignored, session continues
        ws.send_bytes(b"pwd\n")
        # round trip: by the time `pwd` is written the earlier messages were processed in order
        for _ in range(100):
            if b"pwd\n" in process.written:
                break
            asyncio.run(asyncio.sleep(0.02))
    assert process.written == [b"ls\n", b"pwd\n"]
    assert process.sizes == [(100, 30)]
    assert process.closed
    if kind != "docker":
        assert connection.closed
    assert seen["args"]
    actions = access_actions()
    assert f"console.{kind}.open" in actions and f"console.{kind}.close" in actions


@pytest.mark.parametrize("kind", KINDS)
def test_console_sends_exit_on_eof(env, kind):
    process, connection = _new_process(kind, chunks=[b"bye"], eof=True), FakeConnection()
    _install(env, kind, process, connection)
    client = TestClient(main.app)
    with client.websocket_connect(_targets(env)[kind], headers=env["headers"]) as ws:
        assert ws.receive_bytes() == b"bye"
        assert ws.receive_json() == {"type": "exit"}
    assert process.closed
    if kind != "docker":
        assert connection.closed
    assert f"console.{kind}.close" in access_actions()


@pytest.mark.parametrize("kind", KINDS)
def test_console_open_failure_reports_error_and_logs(env, kind):
    mp = env["monkeypatch"]

    async def boom(*a, **k):
        raise RuntimeError("Anmeldung fehlgeschlagen")

    mp.setattr(remote_admin, "open_ssh_pty", boom)
    mp.setattr(remote_admin, "open_remote_docker_exec", boom)
    mp.setattr(docker_admin, "open_exec_session", boom)
    client = TestClient(main.app)
    with client.websocket_connect(_targets(env)[kind], headers=env["headers"]) as ws:
        assert ws.receive_json() == {"type": "error", "message": "Anmeldung fehlgeschlagen"}
        with pytest.raises(Exception) as exc:
            ws.receive_json()
        assert getattr(exc.value, "code", None) == 1011
    entry = next(e for e in db.list_access_log(10) if e["action"] == f"console.{kind}.open")
    assert not entry["ok"]
    assert f"console.{kind}.close" not in access_actions()


@pytest.mark.parametrize("kind", KINDS)
def test_console_cleans_up_when_process_stream_fails(env, kind):
    process, connection = _new_process(kind, chunks=[ConnectionResetError("weg")]), FakeConnection()
    _install(env, kind, process, connection)
    client = TestClient(main.app)
    with client.websocket_connect(_targets(env)[kind], headers=env["headers"]):
        pass  # leaving the block disconnects the browser while the stream error is being handled
    assert process.closed
    if kind != "docker":
        assert connection.closed
