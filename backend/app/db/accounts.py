"""Persistence for accounts (see db/__init__ for the package rules)."""
from __future__ import annotations

import ipaddress
from ._core import _conn, _new_id, _now, _row, _rows
from .systems import get_system


# --------------------------------------------------------------------------------------------
# Accounts (credentials). `secretEnc` is written/read encrypted -- see crypto.py.
# --------------------------------------------------------------------------------------------

def list_accounts(system_id: str | None = None) -> list[dict]:
    sql = "SELECT * FROM accounts"
    params: tuple = ()
    if system_id:
        sql += " WHERE systemId = ?"
        params = (system_id,)
    sql += " ORDER BY label COLLATE NOCASE"
    with _conn() as conn:
        return _rows(conn.execute(sql, params))


def get_account(account_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


def create_account(data: dict) -> dict:
    account_id = _new_id()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO accounts(id, systemId, label, category, username, secretEnc, passphraseEnc, "
            "url, notes, allowProbe, port, updatedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                account_id, data.get("systemId") or None, data.get("label") or "Zugang",
                data.get("category") or "login", data.get("username") or "", data.get("secretEnc") or "",
                data.get("passphraseEnc") or "", data.get("url") or "", data.get("notes") or "",
                1 if data.get("allowProbe") else 0, int(data.get("port") or 0), _now(),
            ),
        )
    return get_account(account_id)  # type: ignore[return-value]


def update_account(account_id: str, patch: dict) -> dict | None:
    allowed = ("systemId", "label", "category", "username", "secretEnc", "passphraseEnc",
               "url", "notes", "allowProbe", "port")
    fields = [f for f in allowed if f in patch]
    if not fields:
        return get_account(account_id)
    assignments = ", ".join(f"{f} = ?" for f in fields)

    def coerce(field: str):
        if field == "systemId":
            return patch[field] or None
        if field == "allowProbe":
            return 1 if patch[field] else 0
        if field == "port":
            return int(patch[field] or 0)
        return patch[field]

    values = [coerce(f) for f in fields]
    with _conn() as conn:
        conn.execute(f"UPDATE accounts SET {assignments}, updatedAt = ? WHERE id = ?", (*values, _now(), account_id))
    return get_account(account_id)


def _assigned_account_ids(conn, system: dict) -> set[str]:
    """Ids of accounts reaching `system` through an `accountAssignments` rule -- assigned straight
    to this system's id, to its `kind` (e.g. every "router"), or to a subnet its IP falls inside.
    Shared by `list_probe_accounts` (which additionally requires `allowProbe`) and
    `list_assigned_accounts` (which doesn't, since that one is for display, not for deciding what
    a scan may actually run)."""
    system_id = system["id"]
    assigned_ids = {
        row["accountId"] for row in conn.execute(
            "SELECT accountId FROM accountAssignments WHERE "
            "(targetType = 'system' AND targetValue = ?) OR "
            "(targetType = 'kind' AND targetValue = ?)",
            (system_id, system.get("kind") or ""),
        )
    }
    ip = (system.get("ip") or "").strip()
    if ip:
        for row in conn.execute(
            "SELECT accountId, targetValue FROM accountAssignments WHERE targetType = 'subnet'"
        ):
            if _ip_in_subnet(ip, row["targetValue"]):
                assigned_ids.add(row["accountId"])
    return assigned_ids


def list_probe_accounts(system_id: str) -> list[dict]:
    """Credentials a human explicitly cleared for authenticated read-only probing of this device --
    either attached directly (`accounts.systemId`) or reaching it through a group/multi-device
    credential profile (see `list_account_assignments`'s own docstring). This is the one place that
    resolution happens, so every caller (pipeline.py's credentialed-probe step, the on-demand
    SNMP/HTTP probes, anything added later) automatically picks up a group-assigned credential
    without having to know the assignment mechanism exists."""
    system = get_system(system_id)
    if system is None:
        return []
    with _conn() as conn:
        direct = _rows(conn.execute(
            "SELECT * FROM accounts WHERE systemId = ? AND allowProbe = 1", (system_id,),
        ))
        assigned_ids = _assigned_account_ids(conn, system)
        assigned: list[dict] = []
        if assigned_ids:
            placeholders = ",".join("?" * len(assigned_ids))
            assigned = _rows(conn.execute(
                f"SELECT * FROM accounts WHERE id IN ({placeholders}) AND allowProbe = 1",
                tuple(assigned_ids),
            ))
    # De-duplicated by id -- an account could be both directly attached to this system and
    # separately assigned to its kind/subnet -- with direct attachment taking priority in the
    # (irrelevant to callers, but deterministic) ordering.
    by_id = {a["id"]: a for a in direct}
    for a in assigned:
        by_id.setdefault(a["id"], a)
    return sorted(by_id.values(), key=lambda a: (a["category"], a["label"].lower()))


def list_assigned_accounts(system_id: str) -> list[dict]:
    """Accounts that reach this device only through an `accountAssignments` rule (kind/subnet/extra
    system), not through `accounts.systemId` directly. For *display* on the device's own page --
    "which credentials apply here and why" -- so, unlike `list_probe_accounts`, not filtered to
    `allowProbe`: a documented-but-not-probed account assigned to a whole device kind should still
    be visible on each device it covers."""
    system = get_system(system_id)
    if system is None:
        return []
    with _conn() as conn:
        assigned_ids = _assigned_account_ids(conn, system)
        if not assigned_ids:
            return []
        placeholders = ",".join("?" * len(assigned_ids))
        rows = _rows(conn.execute(
            f"SELECT * FROM accounts WHERE id IN ({placeholders}) AND (systemId IS NULL OR systemId != ?)",
            (*assigned_ids, system_id),
        ))
    return sorted(rows, key=lambda a: (a["category"], a["label"].lower()))


def _ip_in_subnet(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False  # a malformed IP or CIDR matches nothing rather than raising mid-scan


# Assignment target types set_account_assignments accepts -- see accountAssignments' own schema
# comment for what each means.
_ASSIGNMENT_TARGET_TYPES = {"system", "kind", "subnet"}


def list_account_assignments(account_id: str) -> list[dict]:
    """The group/multi-device targets one credential profile reaches beyond its own primary
    `systemId` -- see accountAssignments' schema comment. Used both by the accounts UI (to show/
    edit them) and to explain, if someone asks, why a device that never had this credential
    directly attached still gets probed with it."""
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM accountAssignments WHERE accountId = ? ORDER BY targetType, targetValue",
            (account_id,),
        ))


def set_account_assignments(account_id: str, assignments: list[dict]) -> list[dict]:
    """Replaces every group/multi-device assignment for one credential profile with exactly the
    given list (each `{"targetType": "system"|"kind"|"subnet", "targetValue": ...}`) -- a whole-list
    replace rather than incremental add/remove, since the edit form always submits the complete
    current set and there is then no separate "remove one" endpoint whose result could drift from
    what the UI shows. An unknown `targetType`, a blank `targetValue`, or (for `subnet`) a value
    that doesn't parse as a CIDR is silently dropped rather than stored as a group that could never
    match anything -- same "no data beats wrong data" posture used elsewhere in this app."""
    with _conn() as conn:
        conn.execute("DELETE FROM accountAssignments WHERE accountId = ?", (account_id,))
        for entry in assignments:
            target_type = entry.get("targetType")
            target_value = (entry.get("targetValue") or "").strip()
            if target_type not in _ASSIGNMENT_TARGET_TYPES or not target_value:
                continue
            if target_type == "subnet":
                try:
                    ipaddress.ip_network(target_value, strict=False)
                except ValueError:
                    continue
            conn.execute(
                "INSERT INTO accountAssignments(id, accountId, targetType, targetValue, createdAt) "
                "VALUES(?,?,?,?,?)",
                (_new_id(), account_id, target_type, target_value, _now()),
            )
    return list_account_assignments(account_id)


def count_assignments_by_account() -> dict[str, int]:
    """Every credential profile's assignment count in one query, so the accounts list can show
    "gilt für N weitere Gruppen/Geräte" without an extra round trip per row -- same pattern
    `count_error_events_by_system` already uses for systems' error-event counts."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT accountId, COUNT(*) AS c FROM accountAssignments GROUP BY accountId"
        ).fetchall()
    return {row["accountId"]: row["c"] for row in rows}


def delete_account(account_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM accountAssignments WHERE accountId = ?", (account_id,))
        # Keep controller-derived documentation and any local notes, but never show it as current
        # once its source credential is gone.
        conn.execute("UPDATE networkResources SET active = 0, updatedAt = ? WHERE sourceAccountId = ?",
                     (_now(), account_id))
        # Reachability facts read through this account are no longer current without it.
        conn.execute("DELETE FROM exposureFacts WHERE sourceAccountId = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
