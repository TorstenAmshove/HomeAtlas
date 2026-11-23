"""`_relay_terminal` sends `{"type":"exit"}` when the process ends (EOF), nothing otherwise."""
import asyncio

from app.routes.remote import _relay_terminal


class FakeWebSocket:
    def __init__(self, *, disconnect_first=False, send_json_raises=False):
        self.events: list = []
        self._disconnect_first = disconnect_first
        self._send_json_raises = send_json_raises

    async def receive(self):
        if self._disconnect_first:
            return {"type": "websocket.disconnect"}
        await asyncio.sleep(3600)

    async def send_bytes(self, data):
        self.events.append(("bytes", data))

    async def send_json(self, data):
        if self._send_json_raises:
            raise RuntimeError("client gone")
        self.events.append(("json", data))


def _reader(chunks):
    items = list(chunks)

    async def read(_n):
        item = items.pop(0) if items else b""
        if isinstance(item, Exception):
            raise item
        return item

    return read


def _run(ws, read):
    asyncio.run(_relay_terminal(ws, read=read, write=lambda d: None, resize=lambda c, r: None))


def test_eof_sends_exit_after_data():
    ws = FakeWebSocket()
    _run(ws, _reader([b"hello", b""]))
    assert ws.events == [("bytes", b"hello"), ("json", {"type": "exit"})]


def test_client_disconnect_first_raises_nothing():
    ws = FakeWebSocket(disconnect_first=True)

    async def read(_n):
        await asyncio.sleep(3600)

    _run(ws, read)
    assert ws.events == []


def test_send_json_failure_is_swallowed():
    ws = FakeWebSocket(send_json_raises=True)
    _run(ws, _reader([b""]))
    assert ws.events == []


def test_read_error_sends_no_exit():
    ws = FakeWebSocket()
    _run(ws, _reader([RuntimeError("boom")]))
    assert ws.events == []
