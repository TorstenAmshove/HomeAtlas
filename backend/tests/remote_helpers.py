"""Shared fixtures-as-functions for the remote-admin tests (WebSocket consoles, container routes,
switching). Plain helpers, no pytest magic, so every test file stays readable on its own."""
from __future__ import annotations

from app import auth, crypto, db


def isolate_crypto(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)


def make_session(role: str = auth.ROLE_ADMIN, totp: bool = True, username: str | None = None) -> str:
    """A real user plus a real session; returns the session token (cookie value)."""
    name = username or f"{role.lower()}-{'totp' if totp else 'plain'}"
    user_id = db.create_user(name, "hash", "salt", role)
    if totp:
        db.update_user(user_id, {"totpEnabled": True})
    return auth.create_session(user_id)


def ws_headers(token: str | None, origin: str | None = "http://testserver") -> dict:
    headers: dict[str, str] = {}
    if origin is not None:
        headers["origin"] = origin
    if token:
        headers["cookie"] = f"{auth.SESSION_COOKIE_NAME}={token}"
    return headers


def make_ssh_system(ip: str = "10.0.0.5", category: str = "sshkey", port: int = 0) -> tuple[dict, dict]:
    system = db.create_system({"name": "Server", "kind": "server", "ip": ip})
    account = db.create_account({"systemId": system["id"], "label": "root", "category": category,
                                 "username": "root", "port": port})
    return system, account


def make_container_system(container_id: str | None = "abc123") -> dict:
    extra = {"docker": {"containerId": container_id}} if container_id else {}
    return db.create_system({"name": "web", "kind": "container", "ip": "10.0.0.9", "extra": extra})


def access_actions() -> list[str]:
    return [e["action"] for e in db.list_access_log(50)]
