"""Device error events. The per-device cap `_ERROR_EVENT_KEEP` lives in `db/__init__.py` and is read
at call time so tests can patch `db._ERROR_EVENT_KEEP`."""
from __future__ import annotations

from .. import db as _pkg
from ._core import _conn, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Device error events -- see deviceErrorEvents' own schema comment for what these are.
# --------------------------------------------------------------------------------------------


def add_device_error_event(system_id: str, level: str, message: str) -> dict | None:
    """Records one scan-time failure against the specific device it happened to, so it shows up
    right where someone looking at *that* device would check first, rather than only in the
    scan-wide log line that scrolls out of view after the next scan. A blank `system_id` is a
    no-op, not an error -- some failures (e.g. a Proxmox host that never resolved to any inventory
    row at all) have nowhere to attach to, and that is a normal, expected case, not a bug."""
    if not system_id:
        return None
    with _conn() as conn:
        event_id = _new_id()
        conn.execute(
            "INSERT INTO deviceErrorEvents(id, systemId, level, message, createdAt) VALUES(?,?,?,?,?)",
            (event_id, system_id, level or "error", (message or "")[:2000], _now()),
        )
        conn.execute(
            "DELETE FROM deviceErrorEvents WHERE systemId = ? AND id NOT IN "
            "(SELECT id FROM deviceErrorEvents WHERE systemId = ? ORDER BY createdAt DESC, rowid DESC LIMIT ?)",
            (system_id, system_id, _pkg._ERROR_EVENT_KEEP),
        )
        return _row(conn.execute("SELECT * FROM deviceErrorEvents WHERE id = ?", (event_id,)).fetchone())


def list_device_error_events(system_id: str, limit: int = 50) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM deviceErrorEvents WHERE systemId = ? ORDER BY createdAt DESC, rowid DESC LIMIT ?",
            (system_id, limit),
        ))


def count_error_events_by_system() -> dict[str, int]:
    """Every device's error-event count in one query, so the systems list can show a warning
    badge without an extra round trip per device -- same pattern `/api/systems` already uses for
    `accountCount`."""
    with _conn() as conn:
        rows = conn.execute("SELECT systemId, COUNT(*) AS c FROM deviceErrorEvents GROUP BY systemId").fetchall()
    return {row["systemId"]: row["c"] for row in rows}
