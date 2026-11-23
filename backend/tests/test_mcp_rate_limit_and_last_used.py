"""#120: per-token rate limit on /api/mcp and a throttled `lastUsedAt` write."""
import asyncio

import pytest

from app import db, limits, mcp_server
from app.db import users


def _call(token: str):
    sent = []

    async def inner(scope, receive, send):
        sent.append("inner")

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
    asyncio.run(mcp_server._BearerAuth(inner)(scope, None, send))
    status = next((m["status"] for m in sent if isinstance(m, dict) and m.get("type") == "http.response.start"), 200)
    headers = next((dict(m["headers"]) for m in sent if isinstance(m, dict) and m.get("type") == "http.response.start"), {})
    return status, headers


@pytest.fixture()
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(mcp_server, "_LIMITER", limits.SlidingWindowLimiter(120, 60, clock=lambda: now[0]))
    return now


def test_token_rate_limited_independently(temp_db, clock):
    a = db.create_api_token("A")["token"]
    b = db.create_api_token("B")["token"]
    for _ in range(120):
        assert _call(a)[0] == 200
    status, headers = _call(a)
    assert status == 429 and int(headers[b"retry-after"]) >= 1
    assert _call(b)[0] == 200
    clock[0] += 61
    assert _call(a)[0] == 200


def test_invalid_token_is_401_and_not_in_limiter(temp_db, clock):
    assert _call("nope")[0] == 401
    assert mcp_server._LIMITER._hits == {}


def test_last_used_throttled(temp_db, monkeypatch):
    token = db.create_api_token("A")["token"]
    current = {"v": None}
    monkeypatch.setattr(users, "_now", lambda: current["v"])

    current["v"] = "2026-01-01T00:00:00Z"
    with users._conn() as conn:
        conn.execute("UPDATE apiTokens SET lastUsedAt = ''")
    assert db.touch_api_token(token)["lastUsedAt"] == "2026-01-01T00:00:00Z"
    current["v"] = "2026-01-01T00:01:00Z"  # exactly 60 s: not written
    assert db.touch_api_token(token)["lastUsedAt"] == "2026-01-01T00:00:00Z"
    current["v"] = "2026-01-01T00:01:01Z"  # > 60 s: written
    assert db.touch_api_token(token)["lastUsedAt"] == "2026-01-01T00:01:01Z"
    with users._conn() as conn:
        conn.execute("UPDATE apiTokens SET lastUsedAt = 'kaputt'")
    assert db.touch_api_token(token)["lastUsedAt"] == "2026-01-01T00:01:01Z"
