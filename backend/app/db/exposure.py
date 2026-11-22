"""Persistence for reachability facts (see db/__init__ for the package rules, ADR-0014).

Only the structured, non-secret fields of a fact are stored; the readers (traefik/cloudflare/file
sources) drop everything else before it gets here. A source's facts are replaced only after a
*successful* read: a failed read must not make the old facts look deleted (that would turn into a
false "orphaned path" in the documentation), so they are flagged stale instead.
"""
from __future__ import annotations

from ._core import _conn, _dump, _new_id, _now, _rows


def list_exposure_facts() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute("SELECT * FROM exposureFacts WHERE active = 1 ORDER BY kind, key"))


def replace_exposure_facts(source: str, account_id: str, facts: list[dict]) -> int:
    """Replaces everything `(source, account_id)` reported with `facts` (each `{kind, key, data}`).

    Call this only after the source was read successfully, including when it legitimately returned
    no facts. `firstSeen` survives for facts that were already known.
    """
    now = _now()
    with _conn() as conn:
        known = {
            (r["kind"], r["key"]): r["firstSeen"]
            for r in conn.execute(
                "SELECT kind, key, firstSeen FROM exposureFacts WHERE source = ? AND sourceAccountId = ?",
                (source, account_id))
        }
        conn.execute("DELETE FROM exposureFacts WHERE source = ? AND sourceAccountId = ?", (source, account_id))
        for fact in facts:
            kind, key = fact.get("kind") or "", fact.get("key") or ""
            if not kind or not key:
                continue
            conn.execute(
                "INSERT INTO exposureFacts(id, source, sourceAccountId, kind, key, data, active, stale, firstSeen, lastSeen) "
                "VALUES(?,?,?,?,?,?,1,0,?,?)",
                (_new_id(), source, account_id, kind, key, _dump(fact.get("data") or {}),
                 known.get((kind, key), now), now),
            )
    return len(facts)


def mark_exposure_facts_stale(source: str, account_id: str) -> None:
    """The source could not be read this time: keep its facts, but flag them as older data."""
    with _conn() as conn:
        conn.execute("UPDATE exposureFacts SET stale = 1 WHERE source = ? AND sourceAccountId = ?",
                     (source, account_id))


def delete_exposure_facts(source: str | None = None, account_id: str | None = None) -> None:
    """Removes facts of a source that was switched off (or of one account)."""
    clauses, params = [], []
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if account_id is not None:
        clauses.append("sourceAccountId = ?")
        params.append(account_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as conn:
        conn.execute("DELETE FROM exposureFacts" + where, tuple(params))


def prune_exposure_facts(source: str, keep_account_ids: list[str]) -> None:
    """Drops facts of `source` whose account is no longer active (deleted, opt-in or switch off)."""
    with _conn() as conn:
        marks = ",".join("?" * len(keep_account_ids))
        clause = f" AND sourceAccountId NOT IN ({marks})" if keep_account_ids else ""
        conn.execute("DELETE FROM exposureFacts WHERE source = ?" + clause, (source, *keep_account_ids))
