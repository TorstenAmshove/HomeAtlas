"""docker_admin against a fake Docker API: start/stop/restart result mapping, log demultiplexing,
the hijacked exec session (fake Unix socket) and resize."""
import asyncio
import json
import struct

import httpx
import pytest

from app import docker_admin


def _patch_httpx(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(docker_admin.httpx, "AsyncClient", factory)


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
@pytest.mark.parametrize("status", [200, 204, 304])
def test_container_actions_hit_the_right_path_and_accept_success(monkeypatch, action, status):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(status)

    _patch_httpx(monkeypatch, handler)
    result = _run(getattr(docker_admin, f"{action}_container")("abc"))
    assert result == {"ok": True, "error": ""}
    assert seen == [("POST", f"/containers/abc/{action}")]


@pytest.mark.parametrize("response, expected", [
    (httpx.Response(404, json={"message": "No such container: abc"}), "No such container: abc"),
    (httpx.Response(500, text="boom, not json"), "boom, not json"),
    (httpx.Response(500, text=""), "HTTP 500"),
])
def test_post_failure_reports_message(monkeypatch, response, expected):
    _patch_httpx(monkeypatch, lambda request: response)
    result = _run(docker_admin.stop_container("abc"))
    assert result["ok"] is False and result["error"] == expected


def test_post_unreachable_docker(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("socket weg")

    _patch_httpx(monkeypatch, handler)
    result = _run(docker_admin.start_container("abc"))
    assert result["ok"] is False and "Docker-API nicht erreichbar" in result["error"]


def _frame(stream: int, payload: bytes) -> bytes:
    return struct.pack(">BxxxI", stream, len(payload)) + payload


def test_demuxer_handles_frames_split_anywhere():
    data = _frame(1, b"hello ") + _frame(2, b"world")
    for cut in range(len(data) + 1):
        demux = docker_admin._Demuxer()
        assert demux.feed(data[:cut]) + demux.feed(data[cut:]) == b"hello world"
    byte_wise = docker_admin._Demuxer()
    assert b"".join(byte_wise.feed(bytes([b])) for b in data) == b"hello world"


def _logs_handler(tty: bool, body: bytes, status: int = 200):
    def handler(request):
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json={"Config": {"Tty": tty}})
        return httpx.Response(status, content=body)
    return handler


def _collect(container="abc"):
    async def go():
        return [c async for c in docker_admin.stream_logs(container)]
    return b"".join(_run(go()))


def test_stream_logs_non_tty_is_demultiplexed(monkeypatch):
    _patch_httpx(monkeypatch, _logs_handler(False, _frame(1, b"out\n") + _frame(2, b"err\n")))
    assert _collect() == b"out\nerr\n"


def test_stream_logs_tty_is_passed_through(monkeypatch):
    _patch_httpx(monkeypatch, _logs_handler(True, b"raw tty output"))
    assert _collect() == b"raw tty output"


def test_stream_logs_http_error_is_reported_inline(monkeypatch):
    _patch_httpx(monkeypatch, _logs_handler(True, b"", status=404))
    assert b"HTTP 404" in _collect()


def test_exec_resize_posts_dimensions(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200)

    _patch_httpx(monkeypatch, handler)
    session = docker_admin.ExecSession(reader=None, writer=None, exec_id="ex1")  # type: ignore[arg-type]
    _run(session.resize(120, 40))
    assert seen == [("POST", "/exec/ex1/resize", {"h": "40", "w": "120"})]


async def _fake_docker(tmp_path, start_status: int, leftover: bytes = b"", after: bytes = b""):
    """Unix-socket server that speaks just enough HTTP for step 2 (the hijack)."""
    received = []

    async def serve(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        received.append(head)
        length = int([ln for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length")][0].split(b":")[1])
        received.append(await reader.readexactly(length))
        reason = b"UPGRADED" if start_status == 101 else b"ERR"
        writer.write(b"HTTP/1.1 %d %s\r\nContent-Type: application/vnd.docker.raw-stream\r\n\r\n%s"
                     % (start_status, reason, leftover))
        await writer.drain()
        if start_status == 101:
            data = await reader.read(100)  # whatever the client types
            received.append(data)
            writer.write(after)
            await writer.drain()
        writer.close()

    sock = str(tmp_path / "d.sock")
    server = await asyncio.start_unix_server(serve, path=sock)
    return server, sock, received


def _exec_create_handler(request):
    assert request.url.path == "/containers/abc/exec"
    body = json.loads(request.content)
    assert body["Tty"] is True and body["Cmd"] == ["/bin/sh"]
    return httpx.Response(201, json={"Id": "ex9"})


def test_open_exec_session_success_delivers_leftover_and_io(tmp_path, monkeypatch):
    async def go():
        server, sock, received = await _fake_docker(tmp_path, 101, leftover=b"/ # ", after=b"done")
        monkeypatch.setattr(docker_admin, "_SOCKET", sock)
        _patch_httpx(monkeypatch, _exec_create_handler)
        async with server:
            session = await docker_admin.open_exec_session("abc")
            first = await session.read()
            session.write(b"ls\n")
            await session.drain()
            second = await asyncio.wait_for(session.read(), 5)
            session.close()
            return session.exec_id, first, second, received

    exec_id, first, second, received = _run(go())
    assert exec_id == "ex9" and first == b"/ # " and second == b"done"
    assert received[0].startswith(b"POST /exec/ex9/start HTTP/1.1") and b"Upgrade: tcp" in received[0]
    assert json.loads(received[1]) == {"Detach": False, "Tty": True}
    assert received[2] == b"ls\n"


def test_open_exec_session_start_failure_raises_and_closes(tmp_path, monkeypatch):
    async def go():
        server, sock, _ = await _fake_docker(tmp_path, 500)
        monkeypatch.setattr(docker_admin, "_SOCKET", sock)
        _patch_httpx(monkeypatch, _exec_create_handler)
        async with server:
            with pytest.raises(RuntimeError, match="HTTP 500"):
                await docker_admin.open_exec_session("abc")

    _run(go())


def test_open_exec_session_create_failure_raises(monkeypatch):
    _patch_httpx(monkeypatch, lambda request: httpx.Response(404, json={"message": "no such container"}))
    with pytest.raises(httpx.HTTPStatusError):
        _run(docker_admin.open_exec_session("abc"))
