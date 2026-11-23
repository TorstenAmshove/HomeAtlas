"""Persistence for users (see db/__init__ for the package rules)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from ._core import _conn, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Users / sessions
# --------------------------------------------------------------------------------------------

_PUBLIC_USER_COLUMNS = "id, username, role, displayName, totpEnabled, createdAt"


def update_user(user_id: str, patch: dict) -> dict | None:
    allowed = ("displayName", "role", "totpSecretEnc", "totpEnabled")
    fields = [f for f in allowed if f in patch]
    if not fields:
        return get_user(user_id)
    assignments = ", ".join(f"{f} = ?" for f in fields)
    values = [(1 if patch[f] else 0) if f == "totpEnabled" else patch[f] for f in fields]
    with _conn() as conn:
        conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*values, user_id))
    return get_user(user_id)


def claim_totp_counter(user_id: str, counter: int) -> bool:
    """Marks a TOTP time step as used. False if it (or a later one) was used already, i.e. the
    code is a replay. One conditional UPDATE, so two concurrent logins with the same code cannot
    both succeed."""
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE users SET totpLastCounter = ? WHERE id = ? AND totpLastCounter < ?",
            (counter, user_id, counter),
        )
        return cursor.rowcount == 1


def invalidate_user_sessions(user_id: str, keep_token: str | None = None) -> int:
    """Forces re-login and returns how many sessions were ended. Used after an admin resets a
    password or a second factor, and after a user changes their own password (there with
    `keep_token` = the current session) -- otherwise an already-open session keeps working with
    the replaced credential, which is not what "reset" is expected to mean."""
    with _conn() as conn:
        if keep_token is None:
            cursor = conn.execute("DELETE FROM sessions WHERE userId = ?", (user_id,))
        else:
            cursor = conn.execute("DELETE FROM sessions WHERE userId = ? AND token != ?",
                                  (user_id, keep_token))
        return cursor.rowcount


def count_users() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def create_user(username: str, password_hash: str, salt: str, role: str, display_name: str = "") -> str:
    user_id = _new_id()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO users(id, username, passwordHash, salt, role, displayName, createdAt) VALUES(?,?,?,?,?,?,?)",
            (user_id, username, password_hash, salt, role, display_name or username, _now()),
        )
    return user_id


def list_users() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(f"SELECT {_PUBLIC_USER_COLUMNS} FROM users ORDER BY createdAt"))


def get_user(user_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute(f"SELECT {_PUBLIC_USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_raw(user_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_username_raw(username: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())


def set_user_password(user_id: str, password_hash: str, salt: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE users SET passwordHash = ?, salt = ? WHERE id = ?", (password_hash, salt, user_id))


def delete_user(user_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE userId = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def create_db_session(token: str, user_id: str, ttl_seconds: int) -> None:
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expiresAt < ?", (_now(),))
        conn.execute("INSERT INTO sessions(token, userId, expiresAt) VALUES(?,?,?)", (token, user_id, expires))


def get_db_session(token: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute(
            "SELECT * FROM sessions WHERE token = ? AND expiresAt > ?", (token, _now())
        ).fetchone())


def delete_db_session(token: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def create_api_token(label: str) -> dict:
    """The raw token is returned here and only here -- the same one-time-reveal shape as the admin
    bootstrap password in auth.py. `list_api_tokens` never selects the `token` column."""
    token_id = _new_id()
    token = secrets.token_urlsafe(32)
    now = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO apiTokens(id, label, token, createdAt, lastUsedAt) VALUES(?,?,?,?,?)",
            (token_id, label, token, now, None),
        )
    return {"id": token_id, "label": label, "token": token, "createdAt": now, "lastUsedAt": None}


def list_api_tokens() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT id, label, createdAt, lastUsedAt FROM apiTokens ORDER BY createdAt DESC"
        ))


def delete_api_token(token_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM apiTokens WHERE id = ?", (token_id,))


_LAST_USED_MIN_AGE_S = 60
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # the format `_now` produces


def _older_than(previous: str | None, now: str, seconds: int) -> bool:
    """True if `previous` is empty/unreadable or more than `seconds` before `now`."""
    try:
        age = datetime.strptime(now, _TS_FORMAT) - datetime.strptime(previous or "", _TS_FORMAT)
    except ValueError:
        return True
    return age.total_seconds() > seconds


def touch_api_token(token: str) -> dict | None:
    """Looked up on every MCP request (see mcp_server.py). Updates `lastUsedAt` on a hit so the
    settings UI can show which tokens are actually in use versus long-forgotten."""
    with _conn() as conn:
        row = _row(conn.execute("SELECT * FROM apiTokens WHERE token = ?", (token,)).fetchone())
        if row is None:
            return None
        now = _now()
        # Throttled: a busy client would otherwise cause a write per request.
        if _older_than(row.get("lastUsedAt"), now, _LAST_USED_MIN_AGE_S):
            conn.execute("UPDATE apiTokens SET lastUsedAt = ? WHERE id = ?", (now, row["id"]))
            row["lastUsedAt"] = now
        return row
