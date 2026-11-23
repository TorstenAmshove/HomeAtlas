"""Login, second factor, roles and the WebSocket gate (#45). Until now the auth path had no backend
tests at all; these cover the rules the spec marks [Muss]: mandatory TOTP, server-side role checks,
brute-force throttling and single-use TOTP codes."""
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


def _from_peer(host: str) -> TestClient:
    """Client whose TCP peer address is `host` (this Starlette's TestClient cannot set it)."""
    async def app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 50000)}
        await main.app(scope, receive, send)
    return TestClient(app)


def _proxied() -> TestClient:
    """Peer is loopback, like nginx talking to the backend (ADR-0003)."""
    return _from_peer("127.0.0.1")


def _login(client: TestClient, username: str, password: str = PASSWORD, code: str = "", ip: str = "10.0.0.5"):
    return client.post("/api/auth/login", json={"username": username, "password": password, "totpCode": code},
                       headers={"X-Real-IP": ip})


# --- login and second factor -----------------------------------------------------------------

def test_login_requires_second_factor_then_succeeds(env):
    _, secret = _user("anna")
    client = _proxied()
    first = _login(client, "anna")
    assert first.status_code == 401 and first.headers.get("X-HomeAtlas-MFA") == "required"
    ok = _login(client, "anna", code=_code(secret))
    assert ok.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["username"] == "anna"


def test_wrong_password_and_wrong_code_are_401(env):
    _, secret = _user("anna")
    client = _proxied()
    assert _login(client, "anna", password="falsch").status_code == 401
    wrong = str((int(_code(secret)) + 1) % 1_000_000).zfill(6)
    assert _login(client, "anna", code=wrong).status_code == 401


def test_totp_code_is_single_use(env):
    _, secret = _user("anna")
    code = _code(secret)
    assert _login(_proxied(), "anna", code=code).status_code == 200
    replay = _login(_proxied(), "anna", code=code)
    assert replay.status_code == 401
    assert replay.headers.get("X-HomeAtlas-MFA") == "required"


def test_older_code_after_newer_one_is_rejected(env):
    _, secret = _user("anna")
    assert _login(_proxied(), "anna", code=_code(secret, drift=0)).status_code == 200
    assert _login(_proxied(), "anna", code=_code(secret, drift=-1)).status_code == 401


def test_unenrolled_session_is_limited_to_enrollment(env):
    _user("bert", totp=False)
    client = _proxied()
    assert _login(client, "bert").status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/systems").status_code == 403
    assert client.post("/api/auth/mfa/setup").status_code == 200


def test_member_cannot_reach_admin_routes(env):
    _, secret = _user("mia", role=auth.ROLE_MEMBER)
    client = _proxied()
    assert _login(client, "mia", code=_code(secret)).status_code == 200
    assert client.get("/api/systems").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/accounts").status_code == 403
    assert client.get("/api/access-log").status_code == 403


# --- throttling ------------------------------------------------------------------------------

def test_lockout_after_repeated_failures_even_with_correct_password(env):
    _, secret = _user("anna")
    client = _proxied()
    for _ in range(5):
        assert _login(client, "anna", password="falsch").status_code == 401
    locked = _login(client, "anna", code=_code(secret))
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    entries = db.list_access_log(10, None, True)
    assert any("gesperrt" in e["detail"] for e in entries)


def test_wrong_codes_count_towards_lockout(env):
    _, secret = _user("anna")
    client = _proxied()
    wrong = str((int(_code(secret)) + 7) % 1_000_000).zfill(6)
    for _ in range(5):
        assert _login(client, "anna", code=wrong).status_code == 401
    assert _login(client, "anna", code=_code(secret)).status_code == 429


def test_lockout_is_per_source_for_the_tight_limit(env):
    _, secret = _user("anna")
    client = _proxied()
    for _ in range(5):
        _login(client, "anna", password="falsch", ip="10.0.0.66")
    assert _login(client, "anna", code=_code(secret), ip="10.0.0.5").status_code == 200


def test_asking_for_the_code_is_not_a_failure(env):
    _user("anna")
    client = _proxied()
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
