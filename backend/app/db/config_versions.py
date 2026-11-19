"""Persistence for config versions (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _new_id, _now, _row, _rows
from .settings import get_settings


# --------------------------------------------------------------------------------------------
# Device configuration backups
# --------------------------------------------------------------------------------------------

# Fallback only -- the effective value is "configVersionKeep" in settings (see SettingsPage.tsx),
# read fresh on every call below so a changed setting applies to the very next backup.
_CONFIG_VERSION_KEEP_DEFAULT = 50


def save_device_config_version(system_id: str, label: str, content_enc: str, source: str) -> dict | None:
    """`content_enc` must already be encrypted by the caller (see probe_auth.persist_config_backups)
    -- this module stays as crypto-agnostic for device configs as it already is for account
    secrets. The caller is also responsible for deciding whether the content actually changed
    (comparing ciphertexts here would be meaningless: encryption is never deterministic)."""
    keep = max(1, min(1000, int(get_settings().get("configVersionKeep") or _CONFIG_VERSION_KEEP_DEFAULT)))
    with _conn() as conn:
        version_id = _new_id()
        conn.execute(
            "INSERT INTO deviceConfigVersions(id, systemId, label, content, source, createdAt) "
            "VALUES(?,?,?,?,?,?)",
            (version_id, system_id, label, content_enc, source, _now()),
        )
        # Unbounded history would grow by a full device export every scan that changes anything.
        conn.execute(
            "DELETE FROM deviceConfigVersions WHERE systemId = ? AND label = ? AND id NOT IN "
            "(SELECT id FROM deviceConfigVersions WHERE systemId = ? AND label = ? "
            "ORDER BY createdAt DESC, rowid DESC LIMIT ?)",
            (system_id, label, system_id, label, keep),
        )
        return _row(conn.execute("SELECT * FROM deviceConfigVersions WHERE id = ?", (version_id,)).fetchone())


def list_device_config_versions(system_id: str) -> list[dict]:
    """Without `content` -- callers that only need the list (to render a table, or to find the
    latest version for a change check) should not have to decrypt every row to get it."""
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT id, systemId, label, source, createdAt, length(content) AS size "
            "FROM deviceConfigVersions WHERE systemId = ? ORDER BY createdAt DESC, rowid DESC",
            (system_id,),
        ))


def get_device_config_version(version_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM deviceConfigVersions WHERE id = ?", (version_id,)).fetchone())
