"""Login, second factor, roles and the WebSocket gate (#45). Until now the auth path had no backend
tests at all; these cover the rules the spec marks [Muss]: mandatory TOTP, server-side role checks,
brute-force throttling and single-use TOTP codes."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, security

PASSWORD = "Korrekt-Pferd-Batterie-9"


@pytest.fixture()
def env(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    monkeypatch.setattr(security, "login_throttle", security.LoginThrottle())
    main.app.dependency_overrides.clear()
    return temp_db


def _user(username: str, role: str = auth.ROLE_ADMIN, totp: bool = True) -> tuple[str, str]:
    salt = "salt-" + username
    user_id = db.create_user(username, auth.hash_password(PASSWORD, salt), salt, role)
    secret = security.generate_totp_secret() if totp else ""
    if totp:
        db.update_user(user_id, {"totpSecretEnc": crypto.encrypt(secret), "totpEnabled": True})
    return user_id, secret


def _code(secret: str, drift: int = 0) -> str:
    return security._code_at(secret, int(time.time()) // 30 + drift)


def _login(client: TestClient, username: str, password: str = PASSWORD, code: str = "", ip: str = "10.0.0.5"):
    return client.post("/api/auth/login", json={"username": username, "password": password, "totpCode": code},
                       headers={"X-Real-IP": ip})


# --- login and second factor -----------------------------------------------------------------

def test_login_requires_second_factor_then_succeeds(env):
    _, secret = _user("anna")
    client = TestClient(main.app)
    first = _login(client, "anna")
    assert first.status_code == 401 and first.headers.get("X-HomeAtlas-MFA") == "required"
    ok = _login(client, "anna", code=_code(secret))
    assert ok.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["username"] == "anna"


def test_wrong_password_and_wrong_code_are_401(env):
    _, secret = _user("anna")
    client = TestClient(main.app)
    assert _login(client, "anna", password="falsch").status_code == 401
    wrong = str((int(_code(secret)) + 1) % 1_000_000).zfill(6)
    assert _login(client, "anna", code=wrong).status_code == 401


def test_totp_code_is_single_use(env):
    _, secret = _user("anna")
    code = _code(secret)
    assert _login(TestClient(main.app), "anna", code=code).status_code == 200
    replay = _login(TestClient(main.app), "anna", code=code)
    assert replay.status_code == 401
    assert replay.headers.get("X-HomeAtlas-MFA") == "required"


def test_older_code_after_newer_one_is_rejected(env):
    _, secret = _user("anna")
    assert _login(TestClient(main.app), "anna", code=_code(secret, drift=0)).status_code == 200
    assert _login(TestClient(main.app), "anna", code=_code(secret, drift=-1)).status_code == 401


def test_unenrolled_session_is_limited_to_enrollment(env):
    _user("bert", totp=False)
    client = TestClient(main.app)
    assert _login(client, "bert").status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/systems").status_code == 403
    assert client.post("/api/auth/mfa/setup").status_code == 200


def test_member_cannot_reach_admin_routes(env):
    _, secret = _user("mia", role=auth.ROLE_MEMBER)
    client = TestClient(main.app)
    assert _login(client, "mia", code=_code(secret)).status_code == 200
    assert client.get("/api/systems").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/accounts").status_code == 403
    assert client.get("/api/access-log").status_code == 403


# --- throttling ------------------------------------------------------------------------------

def test_lockout_after_repeated_failures_even_with_correct_password(env):
    _, secret = _user("anna")
    client = TestClient(main.app)
    for _ in range(5):
        assert _login(client, "anna", password="falsch").status_code == 401
    locked = _login(client, "anna", code=_code(secret))
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    entries = db.list_access_log(10, None, True)
    assert any("gesperrt" in e["detail"] for e in entries)


def test_wrong_codes_count_towards_lockout(env):
    _, secret = _user("anna")
    client = TestClient(main.app)
    wrong = str((int(_code(secret)) + 7) % 1_000_000).zfill(6)
    for _ in range(5):
        assert _login(client, "anna", code=wrong).status_code == 401
    assert _login(client, "anna", code=_code(secret)).status_code == 429


def test_lockout_is_per_source_for_the_tight_limit(env):
    _, secret = _user("anna")
    client = TestClient(main.app)
    for _ in range(5):
        _login(client, "anna", password="falsch", ip="10.0.0.66")
    assert _login(client, "anna", code=_code(secret), ip="10.0.0.5").status_code == 200


def test_asking_for_the_code_is_not_a_failure(env):
    _user("anna")
    client = TestClient(main.app)
    for _ in range(8):
        assert _login(client, "anna").status_code == 401  # password right, code missing
    assert security.login_throttle.retry_after("anna", "10.0.0.5") == 0


def test_throttle_window_expires_and_success_clears():
    now = [1000.0]
    throttle = security.LoginThrottle(clock=lambda: now[0])
    for _ in range(5):
        throttle.record_failure("anna", "1.2.3.4")
    assert throttle.retry_after("anna", "1.2.3.4") > 0
    now[0] += security.LOGIN_WINDOW_SECONDS + 1
    assert throttle.retry_after("anna", "1.2.3.4") == 0
    for _ in range(4):
        throttle.record_failure("Anna", "1.2.3.4")
    throttle.record_success("anna", "1.2.3.4")
    throttle.record_failure("anna", "1.2.3.4")
    assert throttle.retry_after("anna", "1.2.3.4") == 0


def test_ip_limit_covers_many_usernames():
    throttle = security.LoginThrottle(clock=lambda: 0.0)
    for i in range(20):
        throttle.record_failure(f"user{i}", "9.9.9.9")
    assert throttle.retry_after("someone-else", "9.9.9.9") > 0
    assert throttle.retry_after("someone-else", "9.9.9.8") == 0


# --- WebSocket gate --------------------------------------------------------------------------

class _FakeSocket:
    def __init__(self, token: str | None, origin: str = "", host: str = "homeatlas.lan:8280"):
        self.headers = {"origin": origin, "host": host}
        self.cookies = {auth.SESSION_COOKIE_NAME: token} if token else {}


def _session_for(user_id: str) -> str:
    return auth.create_session(user_id)


def test_ws_gate_admin_same_origin_ok_cross_origin_refused(env):
    admin_id, _ = _user("anna")
    token = _session_for(admin_id)
    ok = asyncio.run(main._ws_authenticate(_FakeSocket(token, origin="http://homeatlas.lan:8280")))
    assert ok is not None and ok["username"] == "anna"
    assert asyncio.run(main._ws_authenticate(_FakeSocket(token, origin="http://evil.example"))) is None


def test_ws_gate_refuses_member_unenrolled_and_anonymous(env):
    member_id, _ = _user("mia", role=auth.ROLE_MEMBER)
    unenrolled_id, _ = _user("bert", totp=False)
    origin = "http://homeatlas.lan"
    assert asyncio.run(main._ws_authenticate(_FakeSocket(_session_for(member_id), origin=origin))) is None
    assert asyncio.run(main._ws_authenticate(_FakeSocket(_session_for(unenrolled_id), origin=origin))) is None
    assert asyncio.run(main._ws_authenticate(_FakeSocket(None, origin=origin))) is None


# --- session lifecycle (#116) ----------------------------------------------------------------

def _client_with(token: str) -> TestClient:
    client = TestClient(main.app)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    return client


def _status(token: str) -> int:
    return _client_with(token).get("/api/auth/me").status_code


def test_invalidate_user_sessions_keep_token(env):
    a, _ = _user("anna")
    b, _ = _user("bert")
    keep, other, foreign = auth.create_session(a), auth.create_session(a), auth.create_session(b)
    assert db.invalidate_user_sessions(a, keep_token=keep) == 1
    assert _status(keep) == 200 and _status(other) == 401 and _status(foreign) == 200
    assert db.invalidate_user_sessions(a) == 1
    assert _status(keep) == 401 and _status(foreign) == 200


def test_password_change_ends_other_sessions(env):
    uid, _ = _user("anna")
    other_id, _ = _user("bert")
    a, b, foreign = auth.create_session(uid), auth.create_session(uid), auth.create_session(other_id)
    resp = _client_with(a).post("/api/auth/password",
                                json={"currentPassword": PASSWORD, "newPassword": "Ganz-Neues-Passwort-77x"})
    assert resp.status_code == 200
    assert _status(a) == 200
    assert _status(b) == 401
    assert _status(foreign) == 200  # other users untouched


def test_failed_password_change_keeps_sessions(env):
    uid, _ = _user("anna")
    a, b = auth.create_session(uid), auth.create_session(uid)
    client = _client_with(a)
    assert client.post("/api/auth/password",
                       json={"currentPassword": "falsch", "newPassword": "Ganz-Neues-Passwort-77x"}).status_code == 400
    assert client.post("/api/auth/password",
                       json={"currentPassword": PASSWORD, "newPassword": "a"}).status_code == 400
    assert _status(a) == 200 and _status(b) == 200


def test_admin_mfa_reset_ends_all_target_sessions(env):
    admin_id, _ = _user("anna")
    target_id, _ = _user("bert")
    admin_tok = auth.create_session(admin_id)
    t1, t2 = auth.create_session(target_id), auth.create_session(target_id)
    resp = _client_with(admin_tok).post(f"/api/users/{target_id}/mfa/reset")
    assert resp.status_code == 200
    assert _status(t1) == 401 and _status(t2) == 401
    assert _status(admin_tok) == 200
    fresh = TestClient(main.app)
    assert _login(fresh, "bert").status_code == 200
    assert fresh.get("/api/auth/me").json()["user"]["totpEnabled"] in (False, 0)
    assert fresh.post("/api/auth/mfa/setup").status_code == 200


def test_self_mfa_reset_ends_own_session(env):
    admin_id, _ = _user("anna")
    tok = auth.create_session(admin_id)
    assert _client_with(tok).post(f"/api/users/{admin_id}/mfa/reset").status_code == 200
    assert _status(tok) == 401
    fresh = TestClient(main.app)
    assert _login(fresh, "anna").status_code == 200
    assert fresh.post("/api/auth/mfa/setup").status_code == 200


def test_mfa_reset_unknown_user_is_404_and_ends_nothing(env):
    admin_id, _ = _user("anna")
    tok = auth.create_session(admin_id)
    assert _client_with(tok).post("/api/users/does-not-exist/mfa/reset").status_code == 404
    assert _status(tok) == 200
