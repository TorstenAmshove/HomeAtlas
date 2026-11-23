"""Persistence for scans (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _dump, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Scans
# --------------------------------------------------------------------------------------------

def create_scan(subnets: str) -> str:
    scan_id = _new_id()
    with _conn() as conn:
        conn.execute("INSERT INTO scans(id, startedAt, status, subnets) VALUES(?,?,?,?)", (scan_id, _now(), "running", subnets))
    return scan_id


def create_scan_if_idle(subnets: str) -> str | None:
    """Atomic check-and-insert: a single statement creates the scan only when none is `running`.
    Returns None when one already is, so two concurrent starts can never both succeed."""
    scan_id = _new_id()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO scans(id, startedAt, status, subnets) "
            "SELECT ?, ?, 'running', ? WHERE NOT EXISTS (SELECT 1 FROM scans WHERE status = 'running')",
            (scan_id, _now(), subnets),
        )
        return scan_id if cur.rowcount == 1 else None


def update_scan(scan_id: str, *, phase: str | None = None, progress: int | None = None, log_line: str | None = None) -> None:
    with _conn() as conn:
        if phase is not None:
            conn.execute("UPDATE scans SET phase = ? WHERE id = ?", (phase, scan_id))
        if progress is not None:
            conn.execute("UPDATE scans SET progress = ? WHERE id = ?", (max(0, min(100, progress)), scan_id))
        if log_line:
            conn.execute("UPDATE scans SET log = log || ? WHERE id = ?", (f"{_now()}  {log_line}\n", scan_id))


def finish_scan(scan_id: str, status: str, summary: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE scans SET status = ?, finishedAt = ?, progress = 100, summary = ? WHERE id = ?",
            (status, _now(), _dump(summary), scan_id),
        )


def get_scan(scan_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone())


def latest_scan() -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM scans ORDER BY startedAt DESC LIMIT 1").fetchone())


def list_scans(limit: int = 20) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute("SELECT id, startedAt, finishedAt, status, subnets, summary FROM scans ORDER BY startedAt DESC LIMIT ?", (limit,)))


def running_scan() -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM scans WHERE status = 'running' ORDER BY startedAt DESC LIMIT 1").fetchone())


def abandon_stale_scans() -> None:
    """A container restart mid-scan would otherwise leave a `running` row forever, and the API
    refuses to start a second scan while one is running."""
    with _conn() as conn:
        conn.execute(
            "UPDATE scans SET status = 'failed', finishedAt = ?, phase = 'abgebrochen (Neustart)' WHERE status = 'running'",
            (_now(),),
        )
