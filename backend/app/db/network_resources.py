"""Persistence for network resources (see db/__init__ for the package rules)."""
from __future__ import annotations

import json

from ._core import _conn, _dump, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Controller-synchronized network resources
# --------------------------------------------------------------------------------------------

_NETWORK_RESOURCE_KINDS = {"network", "wifi", "wan"}


def _network_resource_key(source: str, account_id: str, site_id: str, kind: str, external_id: str) -> str:
    return f"{source}:{account_id}:{site_id}:{kind}:{external_id}"


def get_network_resource(resource_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM networkResources WHERE id = ?", (resource_id,)).fetchone())


def list_network_resources(kind: str | None = None, active_only: bool = False) -> list[dict]:
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if active_only:
        clauses.append("active = 1")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM networkResources" + where + " ORDER BY siteName COLLATE NOCASE, kind, name COLLATE NOCASE",
            tuple(params),
        ))


def update_network_resource_manual(resource_id: str, manual_md: str) -> dict | None:
    with _conn() as conn:
        conn.execute("UPDATE networkResources SET manualMd = ?, updatedAt = ? WHERE id = ?",
                     (manual_md, _now(), resource_id))
    return get_network_resource(resource_id)


def sync_network_resources(source_account_id: str, resources: list[dict],
                           complete_scopes: list[tuple[str, str]]) -> list[dict]:
    """Refreshes resources successfully read from a controller.

    `complete_scopes` is deliberately separate from `resources`: a failed endpoint must never make
    its old entries look deleted. Each tuple names one fully listed `(siteExternalId, kind)` scope.
    """
    now = _now()
    refreshed_ids: list[str] = []
    present_by_scope: dict[tuple[str, str], set[str]] = {}
    with _conn() as conn:
        for resource in resources:
            kind = resource.get("kind") or ""
            source = resource.get("source") or "unifi"
            site_id = resource.get("siteExternalId") or ""
            external_id = resource.get("externalId") or ""
            if kind not in _NETWORK_RESOURCE_KINDS or not site_id or not external_id:
                continue
            source_key = _network_resource_key(source, source_account_id, site_id, kind, external_id)
            existing = conn.execute("SELECT id FROM networkResources WHERE sourceKey = ?", (source_key,)).fetchone()
            resource_id = existing["id"] if existing else _new_id()
            conn.execute(
                "INSERT INTO networkResources(id, kind, source, sourceKey, sourceAccountId, ownerSystemId, "
                "siteExternalId, siteName, externalId, name, enabled, active, facts, firstSeen, lastSeen, updatedAt) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(sourceKey) DO UPDATE SET "
                "ownerSystemId = excluded.ownerSystemId, siteName = excluded.siteName, name = excluded.name, "
                "enabled = excluded.enabled, active = 1, facts = excluded.facts, lastSeen = excluded.lastSeen, "
                "updatedAt = excluded.updatedAt",
                (resource_id, kind, source, source_key, source_account_id, resource.get("ownerSystemId") or None,
                 site_id, resource.get("siteName") or "", external_id, resource.get("name") or external_id,
                 1 if resource.get("enabled", True) else 0, 1, _dump(resource.get("facts") or {}), now, now, now),
            )
            refreshed_ids.append(resource_id)
            present_by_scope.setdefault((site_id, kind), set()).add(source_key)

        for site_id, kind in complete_scopes:
            if kind not in _NETWORK_RESOURCE_KINDS or not site_id:
                continue
            present = present_by_scope.get((site_id, kind), set())
            if present:
                placeholders = ",".join("?" * len(present))
                conn.execute(
                    f"UPDATE networkResources SET active = 0, updatedAt = ? WHERE sourceAccountId = ? "
                    f"AND siteExternalId = ? AND kind = ? AND sourceKey NOT IN ({placeholders})",
                    (now, source_account_id, site_id, kind, *present),
                )
            else:
                conn.execute(
                    "UPDATE networkResources SET active = 0, updatedAt = ? WHERE sourceAccountId = ? "
                    "AND siteExternalId = ? AND kind = ?",
                    (now, source_account_id, site_id, kind),
                )
    return [resource for resource_id in refreshed_ids if (resource := get_network_resource(resource_id)) is not None]


def set_wan_ips(source_account_id: str, ips: list[str]) -> int:
    """Attaches WAN addresses (from the classic API) to the WAN rows the account already has.

    The match is by position, so it is only done when the counts agree; with a different number of
    addresses and connections nothing is guessed. Returns the number of rows updated.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, facts FROM networkResources WHERE kind = 'wan' AND active = 1 AND sourceAccountId = ? "
            "ORDER BY siteExternalId, externalId", (source_account_id,)).fetchall()
        if not rows or len(rows) != len(ips):
            return 0
        updated = 0
        for row, ip in zip(rows, ips):
            if not ip:
                continue
            try:
                facts = json.loads(row["facts"] or "{}")
            except (json.JSONDecodeError, TypeError):
                facts = {}
            conn.execute("UPDATE networkResources SET facts = ?, updatedAt = ? WHERE id = ?",
                         (_dump({**facts, "ip": ip}), _now(), row["id"]))
            updated += 1
        return updated
