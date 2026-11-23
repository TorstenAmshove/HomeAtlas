"""Persistence for monitor (see db/__init__ for the package rules)."""
from __future__ import annotations

from .. import db as _pkg
from ._core import _conn, _new_id, _now, _rows


# --------------------------------------------------------------------------------------------
# Live monitoring
# --------------------------------------------------------------------------------------------

def list_monitored_systems() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM systems WHERE monitored = 1 AND (ip != '' OR hostname != '') "
            "ORDER BY CASE importance WHEN 'critical' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, name"
        ))


def record_monitor_state(system_id: str, status: str, detail: str) -> bool:
    """Writes the status and, only on a change, an event. Returns True if the status changed."""
    with _conn() as conn:
        row = conn.execute("SELECT status FROM systems WHERE id = ?", (system_id,)).fetchone()
        if row is None:
            return False
        changed = row["status"] != status
        conn.execute("UPDATE systems SET status = ?, lastSeen = CASE WHEN ? = 'online' THEN ? ELSE lastSeen END "
                     "WHERE id = ?", (status, status, _now(), system_id))
        if changed:
            conn.execute(
                "INSERT INTO monitorEvents(id, systemId, at, status, detail) VALUES(?,?,?,?,?)",
                (_new_id(), system_id, _now(), status, detail[:300]),
            )
            conn.execute(
                "DELETE FROM monitorEvents WHERE systemId = ? AND id NOT IN "
                "(SELECT id FROM monitorEvents WHERE systemId = ? ORDER BY at DESC, rowid DESC LIMIT ?)",
                (system_id, system_id, _pkg._MONITOR_EVENT_KEEP),
            )
    return changed


def list_monitor_events(system_id: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT e.*, s.name AS systemName FROM monitorEvents e LEFT JOIN systems s ON s.id = e.systemId"
    params: list = []
    if system_id:
        sql += " WHERE e.systemId = ?"
        params.append(system_id)
    sql += " ORDER BY e.at DESC, e.rowid DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    with _conn() as conn:
        return _rows(conn.execute(sql, tuple(params)))
