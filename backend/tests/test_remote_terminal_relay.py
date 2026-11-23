"""routes.remote._relay_terminal -- resize messages from the browser are validated; invalid ones
are ignored and never end the terminal session."""
import asyncio
import json

import pytest

from app.routes import remote


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(0.05)
        return {"type": "websocket.disconnect"}

    async def send_bytes(self, data):
        self.sent.append(data)


def _relay(messages):
    resizes, writes = [], []

    async def go():
        async def read(n):
            await asyncio.sleep(3600)

        await remote._relay_terminal(_FakeWebSocket(messages), read=read, write=writes.append,
                                     resize=lambda c, r: resizes.append((c, r)))

    asyncio.run(go())
    return resizes, writes


def _text(payload) -> dict:
    return {"type": "websocket.receive", "text": payload if isinstance(payload, str) else json.dumps(payload)}


_INVALID = [
    {"type": "resize", "cols": "abc", "rows": 24},
    {"type": "resize", "cols": None, "rows": 24},
    {"type": "resize", "cols": 0, "rows": 24},
    {"type": "resize", "cols": 1001, "rows": 24},
    {"type": "resize", "cols": -5, "rows": 24},
    {"type": "resize", "cols": True, "rows": 24},
    {"type": "resize", "cols": 120.5, "rows": 24},
    {"type": "resize", "cols": "120", "rows": 24},
    {"type": "resize", "cols": [], "rows": 24},
    {"type": "resize", "cols": 120, "rows": "x"},
    {"type": "x"},
    "5", [], None, "not json{",
]


@pytest.mark.parametrize("payload", _INVALID)
def test_relay_ignores_invalid_resize(payload):
    resizes, _ = _relay([_text(payload)])
    assert resizes == []


def test_relay_applies_valid_resize():
    resizes, _ = _relay([_text({"type": "resize", "cols": 120, "rows": 40}),
                         _text({"type": "resize", "cols": 100})])
    assert resizes == [(120, 40), (100, 24)]


def test_relay_keeps_forwarding_after_invalid_resize():
    _, writes = _relay([_text({"type": "resize", "cols": "abc"}),
                        {"type": "websocket.receive", "bytes": b"ls\n"}])
    assert writes == [b"ls\n"]
