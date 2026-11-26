"""#251: session and MCP tokens are stored only as SHA-256 hex; the raw value lives in the cookie or
is revealed once when an MCP token is created. Legacy raw rows never authenticate and are dropped."""
import hashlib

from app import auth, db
from app.db import _core

from tests.test_auth_login import _code, _login, _proxied, _user, env  # noqa: F401  (fixture reuse)
from tests.test_mcp_rate_limit_and_last_used import _call


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _all_values(table: str) -> list[str]:
    with _core._conn() as conn:
        return [str(v) for row in conn.execute(f"SELECT * FROM {table}").fetchall() for v in tuple(row)]


def test_no_raw_token_stored(temp_db):
    uid = db.create_user("anna", "h", "s", "ADMIN")
    raw_session = "roher-sitzungswert-" + "x" * 30
    db.create_db_session(raw_session, uid, 3600)
    created = db.create_api_token("Laptop")
    for table, raw in (("sessions", raw_session), ("apiTokens", created["token"])):
        values = _all_values(table)
        assert not any(raw in v for v in values), table
        assert _sha(raw) in values, table


def test_session_roundtrip_and_expiry(temp_db):
    uid = db.create_user("anna", "h", "s", "ADMIN")
    db.create_db_session("abc", uid, 3600)
    assert db.get_db_session("abc")["userId"] == uid
    db.delete_db_session("abc")
    assert db.get_db_session("abc") is None
    db.create_db_session("old", uid, -10)
    assert db.get_db_session("old") is None


def test_invalidate_keep_token(temp_db):
    a = db.create_user("anna", "h", "s", "ADMIN")
    b = db.create_user("bert", "h", "s", "ADMIN")
    for token, uid in (("a1", a), ("a2", a), ("b1", b)):
        db.create_db_session(token, uid, 3600)
    assert db.invalidate_user_sessions(a, keep_token="a1") == 1
    assert db.get_db_session("a1") and db.get_db_session("a2") is None and db.get_db_session("b1")
    assert db.invalidate_user_sessions(a, keep_token="falsch") == 1
    assert db.get_db_session("a1") is None and db.get_db_session("b1")
    db.create_db_session("a3", a, 3600)
    assert db.invalidate_user_sessions(a) == 1 and db.get_db_session("b1")


def test_http_login_me_logout(env):  # noqa: F811
    _, secret = _user("anna")
    client = _proxied()
    assert _login(client, "anna", code=_code(secret)).status_code == 200
    cookie = next(iter(client.cookies.values()))
    assert not any(cookie in v for v in _all_values("sessions"))
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.set(auth.SESSION_COOKIE_NAME, cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_api_token_auth_and_last_used(temp_db):
    raw = db.create_api_token("Laptop")["token"]
    row = db.touch_api_token(raw)
    assert row["label"] == "Laptop" and row["lastUsedAt"] and "token" not in row
    assert _call(raw)[0] == 200


def test_api_token_rejects_stored_hash_and_wrong_values(temp_db):
    raw = db.create_api_token("Laptop")["token"]
    assert db.touch_api_token("falsch") is None
    assert db.touch_api_token(_sha(raw)) is None
    assert db.touch_api_token("") is None
    assert _call(_sha(raw))[0] == 401
    listed = str(db.list_api_tokens())
    assert raw not in listed and _sha(raw) not in listed


def test_legacy_plaintext_rows_rejected_and_removed(temp_db):
    uid = db.create_user("anna", "h", "s", "ADMIN")
    legacy = "L" * 43  # secrets.token_urlsafe(32) length, stored raw before #251
    with _core._conn() as conn:
        conn.execute("INSERT INTO sessions(token, userId, expiresAt) VALUES(?,?,?)",
                     (legacy, uid, "2999-01-01T00:00:00Z"))
        conn.execute("INSERT INTO apiTokens(id, label, token, createdAt) VALUES('t1','alt',?,'2020-01-01T00:00:00Z')",
                     (legacy,))
    assert db.get_db_session(legacy) is None and db.touch_api_token(legacy) is None
    db.create_db_session("neu", uid, 3600)
    fresh = db.create_api_token("neu")["token"]
    db.init_db()
    db.init_db()  # idempotent
    assert legacy not in _all_values("sessions") and legacy not in _all_values("apiTokens")
    assert db.get_db_session("neu") and db.touch_api_token(fresh)
