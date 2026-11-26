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


def count_error_events_by_system() -> dict[str, dict[str, int]]:
    """Every device's open (unacknowledged) events in one query, split into `error` and `warning`
    (#254), so the systems list can show a red and a yellow badge without an extra round trip per
    device -- same pattern `/api/systems` already uses for `accountCount`. Anything that is not
    `warning` counts as an error (`add_device_error_event` normalises unknown levels to `error`).
    Devices without open events are absent."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT systemId, SUM(level <> 'warning') AS e, SUM(level = 'warning') AS w FROM deviceErrorEvents"
            " WHERE acknowledgedAt IS NULL GROUP BY systemId").fetchall()
    return {row["systemId"]: {"error": row["e"] or 0, "warning": row["w"] or 0} for row in rows}


# Message prefix of the monitor's outage warning (monitor.py). Shared here so the monitor writes and
# `acknowledge_offline_warnings` recognises the same text -- also for events written before #254.
OFFLINE_MESSAGE_PREFIX = "Nicht mehr erreichbar"


def acknowledge_offline_warnings(system_id: str) -> int:
    """Acknowledges the device's open "Nicht mehr erreichbar" warnings once the monitor sees it
    online again (#254). Errors and other warnings stay open; already acknowledged events keep their
    first timestamp. Prefix compared with `substr`, not LIKE, so `%`/`_` in a message cannot widen it."""
    with _conn() as conn:
        return conn.execute(
            "UPDATE deviceErrorEvents SET acknowledgedAt = ? WHERE systemId = ? AND acknowledgedAt IS NULL"
            " AND level = 'warning' AND substr(message, 1, length(?)) = ?",
            (_now(), system_id, OFFLINE_MESSAGE_PREFIX, OFFLINE_MESSAGE_PREFIX)).rowcount


def acknowledge_device_error_events(system_id: str, event_id: str | None = None) -> int:
    """Marks open events of one device as acknowledged (one event, or all when `event_id` is None).
    Already acknowledged events keep their first timestamp; an event that belongs to another device
    is never touched. Returns how many were newly acknowledged."""
    sql = "UPDATE deviceErrorEvents SET acknowledgedAt = ? WHERE systemId = ? AND acknowledgedAt IS NULL"
    params: list = [_now(), system_id]
    if event_id is not None:
        sql += " AND id = ?"
        params.append(event_id)
    with _conn() as conn:
        return conn.execute(sql, params).rowcount
