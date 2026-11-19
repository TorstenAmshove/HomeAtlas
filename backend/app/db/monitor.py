"""Persistence for monitor (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _new_id, _now, _rows


# --------------------------------------------------------------------------------------------
# Live monitoring
# --------------------------------------------------------------------------------------------

def ensure_monitoring_for_critical() -> int:
    """Enrols every critical device that has an address into the live monitor.

    Runs on startup and before each monitor round, not just at scan time. Otherwise a device that
    a human marks as critical in the UI is never polled and sits at status "unknown" forever --
    which is exactly what the dashboard's "most important devices" list was showing.
    """
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE systems SET monitored = 1 "
            "WHERE importance = 'critical' AND monitored = 0 AND (ip != '' OR hostname != '')"
        )
        return cursor.rowcount or 0


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
