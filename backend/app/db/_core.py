"""Connection, JSON-column coding and schema -- the base every other `db/` module builds on.

Imports nothing from sibling modules. `DB_PATH` is NOT defined here: it lives in `db/__init__.py`
and is read at call time (see `_conn`/`init_db`), so tests that monkeypatch `db.DB_PATH` reach
every submodule."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


# Columns stored as JSON text. Kept in one place so `_row` and the writers can't drift apart.
_JSON_COLUMNS = {"openPorts", "services", "extra", "summary", "toolCalls", "tags", "answers",
                  "providerRaw", "monitorPorts", "facts", "data"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    from .. import db as _pkg  # DB_PATH lives in db/__init__ so monkeypatching `db.DB_PATH` works
    conn = sqlite3.connect(_pkg.DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in _JSON_COLUMNS:
            try:
                value = json.loads(value) if value else None
            except (json.JSONDecodeError, TypeError):
                value = None
        out[key] = value
    return out


def _rows(rows) -> list[dict]:
    return [r for r in (_row(row) for row in rows) if r is not None]


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    passwordHash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL,
    displayName TEXT NOT NULL DEFAULT '',
    -- Second factor: the shared TOTP secret, encrypted like every other secret. `totpEnabled`
    -- only flips to 1 after the user has proved a working code, so a half-finished setup can
    -- never lock anyone out.
    totpSecretEnc TEXT NOT NULL DEFAULT '',
    totpEnabled INTEGER NOT NULL DEFAULT 0,
    createdAt TEXT NOT NULL
);

-- Who did what, when. Deliberately includes reads of stored passwords: for a credential store,
-- "someone looked at the router password at 03:12" is exactly the event worth having later.
CREATE TABLE IF NOT EXISTS accessLog (
    id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    userId TEXT,
    username TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    userAgent TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_accesslog_at ON accessLog(at DESC);

-- Only status *changes* from the live monitor. Writing every poll would add ~8600 rows per device
-- per day and say nothing; an up/down transition is the thing anyone ever looks for.
CREATE TABLE IF NOT EXISTS monitorEvents (
    id TEXT PRIMARY KEY,
    systemId TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_monitorevents_system ON monitorEvents(systemId, at DESC);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    userId TEXT NOT NULL,
    expiresAt TEXT NOT NULL
);

-- Long-lived credentials for the MCP server (see mcp_server.py) -- external LLM clients have no
-- browser session to present, so they authenticate with one of these instead. Stored raw, same as
-- session tokens above: server-generated, high-entropy, and a database compromise already means
-- every session and password is exposed too, so hashing here buys nothing sessions don't already
-- forgo.
CREATE TABLE IF NOT EXISTS apiTokens (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    createdAt TEXT NOT NULL,
    lastUsedAt TEXT
);
CREATE INDEX IF NOT EXISTS idx_apitokens_token ON apiTokens(token);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Every documented thing: router, switch, access point, server, container, VM, PC, phone,
-- thermostat, heat pump, ... `kind` drives which documentation chapter it lands in (see docs.py).
CREATE TABLE IF NOT EXISTS systems (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'other',
    name TEXT NOT NULL,
    hostname TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    mac TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    descriptionMd TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    -- Link to the manufacturer's manual/support page for this exact model. Separate from `url`,
    -- which is the device's own web interface -- when something is broken you often need both.
    docUrl TEXT NOT NULL DEFAULT '',
    -- The household's *own* documentation for this specific instance (a wiki page, runbook,
    -- compose-repo README, ...) -- distinct from docUrl's manufacturer manual, which is the same
    -- for every unit of a model and says nothing about what this particular one is actually for.
    -- Populated automatically from a `Doc:`/`URL:` line in a Proxmox guest's Notes field (see
    -- proxmox_probe.parse_notes) but editable by hand for anything else.
    docLink TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    importance TEXT NOT NULL DEFAULT 'normal',
    parentId TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    discovered INTEGER NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    discoverySource TEXT NOT NULL DEFAULT '',
    -- Stable re-discovery identity, assigned by discovery.py: 'mac:<mac>' where we have one,
    -- 'ip:<addr>' for hosts off the local L2 segment, 'docker:<container-id>'. Empty for
    -- hand-created entries, which fall back to their row id below so they never collide.
    discoveryKey TEXT NOT NULL DEFAULT '',
    -- Live monitoring: polled every few seconds rather than once per scan.
    monitored INTEGER NOT NULL DEFAULT 0,
    monitorPorts TEXT,
    identityKey TEXT GENERATED ALWAYS AS
        (CASE WHEN discoveryKey != '' THEN discoveryKey ELSE 'id:' || id END) VIRTUAL,
    openPorts TEXT,
    services TEXT,
    tags TEXT,
    extra TEXT,
    firstSeen TEXT NOT NULL,
    lastSeen TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_systems_kind ON systems(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_systems_identity ON systems(identityKey);

-- Identities of rows folded into another system by merge_systems. A later scan that finds one of
-- these keys is attributed to the surviving row instead of re-creating the merged-away duplicate.
-- aliasKey is a discoveryKey or 'mac:<mac>'; ip/mac are what was seen under it ("Weitere IPs").
CREATE TABLE IF NOT EXISTS systemAliases (
    aliasKey TEXT PRIMARY KEY,
    systemId TEXT NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    mac TEXT NOT NULL DEFAULT '',
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_systemaliases_system ON systemAliases(systemId);

-- Pairs a human marked "not a duplicate"; idA < idB so a pair has exactly one row.
CREATE TABLE IF NOT EXISTS duplicateDismissals (
    idA TEXT NOT NULL,
    idB TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    PRIMARY KEY (idA, idB)
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    systemId TEXT,
    label TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'login',
    username TEXT NOT NULL DEFAULT '',
    secretEnc TEXT NOT NULL DEFAULT '',
    -- Passphrase for an SSH private key held in secretEnc, encrypted the same way.
    passphraseEnc TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    -- Opt-in, default off: may HomeAtlas use this credential to log in and read? Nothing is ever
    -- used for authenticated probing unless a human explicitly ticks this per credential.
    allowProbe INTEGER NOT NULL DEFAULT 0,
    -- SSH port / target overrides for credentials whose device isn't on the default port.
    port INTEGER NOT NULL DEFAULT 0,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_system ON accounts(systemId);

-- Controller-synchronized network definitions (VLANs, WLANs and WAN interfaces). Technical
-- fields are refreshed from the controller, while `manualMd` remains local documentation.
CREATE TABLE IF NOT EXISTS networkResources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    sourceKey TEXT NOT NULL UNIQUE,
    sourceAccountId TEXT NOT NULL,
    ownerSystemId TEXT,
    siteExternalId TEXT NOT NULL,
    siteName TEXT NOT NULL DEFAULT '',
    externalId TEXT NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    emptyScans INTEGER NOT NULL DEFAULT 0,
    facts TEXT,
    manualMd TEXT NOT NULL DEFAULT '',
    firstSeen TEXT NOT NULL,
    lastSeen TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_networkresources_kind ON networkResources(kind, active);
CREATE INDEX IF NOT EXISTS idx_networkresources_account ON networkResources(sourceAccountId);

-- Normalised reachability facts (ADR-0014): one row per fact read from one source/account. `data`
-- holds only the allowlisted, non-secret fields of the fact's kind (see exposure.py); raw files and
-- API answers are never stored. `stale = 1` means the last read of that source failed and the row
-- is older data, never silently deleted.
CREATE TABLE IF NOT EXISTS exposureFacts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sourceAccountId TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    stale INTEGER NOT NULL DEFAULT 0,
    firstSeen TEXT NOT NULL,
    lastSeen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exposurefacts_source ON exposureFacts(source, sourceAccountId);

-- Normalised firewall facts (ADR-0017): zones, policies and address/port groups of the UniFi
-- gateway (later: nftables rules). Same rules as exposureFacts: `data` holds only allowlisted,
-- non-secret fields, raw answers are never stored, `stale = 1` marks data of a failed read.
CREATE TABLE IF NOT EXISTS firewallFacts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sourceAccountId TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    stale INTEGER NOT NULL DEFAULT 0,
    firstSeen TEXT NOT NULL,
    lastSeen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_firewallfacts_source ON firewallFacts(source, sourceAccountId);

-- Lets one credential profile (an `accounts` row) additionally apply to more than the single
-- device its own `systemId` points at -- a whole device kind ("every switch"), a subnet ("every
-- device on 192.168.2.0/24"), or further individual systems beyond the primary one. See
-- db.list_probe_accounts for how this is resolved at scan time and set_account_assignments for
-- how it is written; no ON DELETE CASCADE (this codebase declares no FK constraints anywhere --
-- see delete_account/delete_system for the manual cleanup convention instead).
CREATE TABLE IF NOT EXISTS accountAssignments (
    id TEXT PRIMARY KEY,
    accountId TEXT NOT NULL,
    -- 'system' (targetValue = a systems.id), 'kind' (targetValue = a systems.kind, e.g. "router"),
    -- or 'subnet' (targetValue = a CIDR string, e.g. "192.168.2.0/24").
    targetType TEXT NOT NULL,
    targetValue TEXT NOT NULL,
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accountassign_account ON accountAssignments(accountId);
CREATE INDEX IF NOT EXISTS idx_accountassign_target ON accountAssignments(targetType, targetValue);

-- Every version of every documentation page, so a regenerate is never destructive and older
-- states stay reachable. Written before each change, not after -- a snapshot taken afterwards
-- would already be the new text.
CREATE TABLE IF NOT EXISTS docPageVersions (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    bodyMd TEXT NOT NULL,
    manualMd TEXT NOT NULL DEFAULT '',
    generated INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL DEFAULT '',
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docversions_slug ON docPageVersions(slug, createdAt DESC);

-- Backups of a device's own textual configuration (Mikrotik `/export`, Aruba `show
-- running-config`, ...), view-only history modeled on docPageVersions. `content` is encrypted at
-- rest (see probe_auth.persist_config_backups) -- unlike documentation text, a device export can
-- contain secrets (SNMP community strings, RADIUS shared secrets, WiFi keys). Never written back
-- to the device: see the read-only invariant in probe_auth.py's module docstring.
CREATE TABLE IF NOT EXISTS deviceConfigVersions (
    id TEXT PRIMARY KEY,
    systemId TEXT NOT NULL,
    label TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    createdAt TEXT NOT NULL
);

-- One row per scan-time failure a device was the subject of -- an SSH timeout, a Proxmox auth
-- error, a monitored device going down, and so on (see pipeline.py/monitor.py's
-- db.add_device_error_event calls). Kept as its own history table, not a field on `systems`,
-- for the same reason deviceConfigVersions is: it is something that accumulates over many scans,
-- not a single current value an upsert would just overwrite. Never contains a secret -- callers
-- pass through whatever error message probe_auth/proxmox_probe/monitor.py already produced for a
-- human to read, none of which include credentials (see those modules' own invariants).
CREATE TABLE IF NOT EXISTS deviceErrorEvents (
    id TEXT PRIMARY KEY,
    systemId TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    -- NULL = open; set by an admin acknowledging it. Only open events count toward the badge.
    acknowledgedAt TEXT
);
CREATE INDEX IF NOT EXISTS idx_errorevents_system ON deviceErrorEvents(systemId, createdAt DESC);
CREATE INDEX IF NOT EXISTS idx_configversions_system ON deviceConfigVersions(systemId, createdAt DESC);

CREATE TABLE IF NOT EXISTS docPages (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    bodyMd TEXT NOT NULL DEFAULT '',
    -- The household's own notes for this chapter. Held in its own column rather than as a marked
    -- region inside bodyMd: generation then cannot damage it by construction, instead of relying
    -- on a parser to find and re-splice a block every time the layout changes.
    manualMd TEXT NOT NULL DEFAULT '',
    intro TEXT NOT NULL DEFAULT '',
    generated INTEGER NOT NULL DEFAULT 1,
    sortOrder INTEGER NOT NULL DEFAULT 0,
    updatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    startedAt TEXT NOT NULL,
    finishedAt TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    subnets TEXT NOT NULL DEFAULT '',
    progress INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT '',
    summary TEXT,
    log TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Neue Unterhaltung',
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chatMessages (
    id TEXT PRIMARY KEY,
    chatId TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    toolCalls TEXT,
    -- Verbatim provider payload for an assistant turn (see llm_providers.ChatResult.provider_raw).
    -- Anthropic validates a signature on the thinking blocks it emits alongside tool calls, so the
    -- next turn has to replay them exactly -- they cannot be rebuilt from `toolCalls`.
    providerRaw TEXT,
    toolCallId TEXT,
    name TEXT,
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chatmsg_chat ON chatMessages(chatId);
"""

# Columns added after the first release. `CREATE TABLE IF NOT EXISTS` does nothing to a table that
# already exists, so an installation that predates a column would keep the old shape and every
# query naming it would fail -- these are applied explicitly on startup.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("deviceErrorEvents", "acknowledgedAt", "TEXT"),
    ("systems", "docUrl", "TEXT NOT NULL DEFAULT ''"),
    ("accounts", "passphraseEnc", "TEXT NOT NULL DEFAULT ''"),
    ("accounts", "allowProbe", "INTEGER NOT NULL DEFAULT 0"),
    ("accounts", "port", "INTEGER NOT NULL DEFAULT 0"),
    ("docPages", "manualMd", "TEXT NOT NULL DEFAULT ''"),
    ("docPageVersions", "manualMd", "TEXT NOT NULL DEFAULT ''"),
    ("users", "totpSecretEnc", "TEXT NOT NULL DEFAULT ''"),
    ("users", "totpEnabled", "INTEGER NOT NULL DEFAULT 0"),
    # Owner of a conversation (#49). NULL for chats created before ownership existed: those are
    # visible to admins only.
    ("chats", "userId", "TEXT"),
    # Highest TOTP time-step counter already used to log in -- a code is single-use (RFC 6238 §5.2).
    ("users", "totpLastCounter", "INTEGER NOT NULL DEFAULT 0"),
    ("systems", "monitored", "INTEGER NOT NULL DEFAULT 0"),
    ("systems", "monitorPorts", "TEXT"),
    ("systems", "docLink", "TEXT NOT NULL DEFAULT ''"),
    ("chatMessages", "durationMs", "INTEGER"),
    # Consecutive complete-but-empty controller reads of a resource's scope (#139).
    ("networkResources", "emptyScans", "INTEGER NOT NULL DEFAULT 0"),
)


def init_db() -> None:
    from .. import db as _pkg

    os.makedirs(os.path.dirname(_pkg.DB_PATH) or ".", exist_ok=True)
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        for table, column, ddl in _ADDED_COLUMNS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

        # ADR-0016: the scan reads the classic UniFi API with the `unifi` account's API key; the
        # former login-based category was never used and is removed, same steps as delete_account.
        for old in conn.execute("SELECT id FROM accounts WHERE category = 'unifi_classic'").fetchall():
            conn.execute("DELETE FROM accountAssignments WHERE accountId = ?", (old["id"],))
            conn.execute("UPDATE networkResources SET active = 0, updatedAt = ? WHERE sourceAccountId = ?",
                         (_now(), old["id"]))
            conn.execute("DELETE FROM exposureFacts WHERE sourceAccountId = ?", (old["id"],))
            conn.execute("DELETE FROM accounts WHERE id = ?", (old["id"],))
