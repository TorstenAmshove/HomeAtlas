"""Persistence for access log (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _new_id, _now, _rows


# --------------------------------------------------------------------------------------------
# Access log
# --------------------------------------------------------------------------------------------

_ACCESS_LOG_KEEP = 5000


def log_access(action: str, *, user: dict | None = None, username: str = "", detail: str = "",
               ip: str = "", user_agent: str = "", ok: bool = True) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO accessLog(id, at, userId, username, action, detail, ip, userAgent, ok) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (_new_id(), _now(), (user or {}).get("id"), username or (user or {}).get("username", ""),
             action, detail[:500], ip[:60], user_agent[:200], 1 if ok else 0),
        )
        conn.execute(
            "DELETE FROM accessLog WHERE id NOT IN "
            "(SELECT id FROM accessLog ORDER BY at DESC, rowid DESC LIMIT ?)",
            (_ACCESS_LOG_KEEP,),
        )


def list_access_log(limit: int = 200, action: str | None = None, only_failures: bool = False) -> list[dict]:
    sql = "SELECT * FROM accessLog"
    clauses, params = [], []
    if action:
        clauses.append("action = ?")
        params.append(action)
    if only_failures:
        clauses.append("ok = 0")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(1000, limit)))
    with _conn() as conn:
        return _rows(conn.execute(sql, tuple(params)))


def access_log_actions() -> list[str]:
    with _conn() as conn:
        return [r["action"] for r in conn.execute("SELECT DISTINCT action FROM accessLog ORDER BY action")]
