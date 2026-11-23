"""Settings -- one JSON blob under a single key, patched wholesale. `strip_probe_facts`, `rewrite_doc_bodies` and
`redact_tool_messages` are one-time settings migrations that touch other tables (docPages,
chatMessages, systems); they stay here with the settings they migrate for."""
from __future__ import annotations

import json
from typing import Any
from ._core import _conn, _dump


# --------------------------------------------------------------------------------------------
# Settings -- one JSON blob under a single key, patched wholesale.
# --------------------------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "homeName": "Mein Zuhause",
    "setupCompleted": False,
    # LLM
    "llmProvider": "DEEPSEEK",
    "geminiApiKey": "", "geminiModel": "auto",
    "claudeApiKey": "", "claudeModel": "auto", "claudeBaseUrl": "",
    "openAiApiKey": "", "openAiModel": "auto", "openAiBaseUrl": "",
    "deepseekApiKey": "", "deepseekModel": "auto", "deepseekBaseUrl": "",
    "ollamaApiKey": "", "ollamaModel": "auto", "ollamaBaseUrl": "",
    "providerModelCache": {},
    "systemPromptOverride": "",
    # Discovery
    "scanSubnets": [],          # free-text additions; empty + nothing checked -> host interfaces
    "scanControllerNetworkIds": [],    # networkResources IDs (UniFi networks) ticked for scanning
    "scanControllerNetworksSeen": [],  # IDs shown at last save; active network not in here = "neu"
    "scanTimeoutMs": 700,
    "scanConcurrency": 128,
    "scanEnableMdns": True,
    "scanEnableSsdp": True,
    "scanEnableDocker": True,
    "scanEnableUnifi": True,
    "scanEnableOmada": True,
    "scanEnableProxmox": True,
    "scanEnableAdguard": True,
    "scanEnableTraefik": True,
    "scanEnableUnifiClassic": True,
    "scanEnableExposureFiles": True,
    # Contacts outside the LAN (ADR-0014): off until switched on deliberately.
    "scanEnableCloudflare": False,
    "scanEnablePublicDns": False,
    # Firewall rules (ADR-0017): off until switched on deliberately, on top of the per-account opt-in.
    "scanEnableFirewallUnifi": False,
    "scanEnableFirewallNft": False,
    "scanEnableHttpBanner": True,
    "scanUseLlm": True,
    "scanExcludeIps": [],
    # Individual hosts outside the scanned subnets -- a router on another segment, a VM behind a
    # bridge. Addresses of hand-created devices are added automatically (see pipeline).
    "scanExtraTargets": [],
    "scanUseCredentials": True,
    "scanAutoEnabled": False,
    "scanAutoIntervalHours": 24,
    "configVersionKeep": 50,
    # Live monitoring
    "monitorEnabled": True,
    "monitorIntervalSeconds": 10,
    "monitorTimeoutMs": 1500,
    # Fallback credential for authenticated probing, used only where a device has no credential of
    # its own. Stored encrypted inside this blob, same as the API keys, and masked by the API.
    "defaultCredentialEnabled": False,
    "defaultCredentialUsername": "",
    "defaultCredentialIsKey": False,
    "defaultCredentialSecretEnc": "",
    "defaultCredentialPassphraseEnc": "",
    "defaultCredentialPort": 0,
    # Names resolved by the DNS self-test. External by design -- resolving only local names would
    # pass even when the forwarder to the internet is broken, which is the common failure.
    "dnsTestNames": ["www.google.com", "heise.de", "github.com"],
}

_SETTINGS_KEY = "app"


def get_settings() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (_SETTINGS_KEY,)).fetchone()
    stored = {}
    if row:
        try:
            stored = json.loads(row["value"])
        except json.JSONDecodeError:
            stored = {}
    return {**DEFAULT_SETTINGS, **stored}


# --------------------------------------------------------------------------------------------
# One-time clean-up of secrets older versions stored in readable places (see
# routes.settings._migrate_plaintext_secrets). Idempotent; none of these touch `updatedAt`, since nothing the
# household maintains changes.
# --------------------------------------------------------------------------------------------

def strip_probe_facts(fact_keys: set[str] | frozenset[str]) -> int:
    """Removes the given fact keys from every system's `extra.probe`. Returns rows changed."""
    changed = 0
    with _conn() as conn:
        rows = conn.execute("SELECT id, extra FROM systems WHERE extra IS NOT NULL").fetchall()
        for row in rows:
            try:
                extra = json.loads(row["extra"]) if row["extra"] else None
            except json.JSONDecodeError:
                continue
            probe = (extra or {}).get("probe")
            if not isinstance(probe, dict):
                continue
            dirty = False
            for result in probe.values():
                facts = result.get("facts") if isinstance(result, dict) else None
                if isinstance(facts, dict):
                    for key in [k for k in facts if k in fact_keys]:
                        del facts[key]
                        dirty = True
            if dirty:
                conn.execute("UPDATE systems SET extra = ? WHERE id = ?", (_dump(extra), row["id"]))
                changed += 1
    return changed


def rewrite_doc_bodies(transform) -> int:
    """Applies `transform(bodyMd) -> bodyMd` to every doc page and every stored page version.
    Returns how many rows changed."""
    changed = 0
    with _conn() as conn:
        for table in ("docPages", "docPageVersions"):
            for row in conn.execute(f"SELECT id, bodyMd FROM {table}").fetchall():
                new_body = transform(row["bodyMd"] or "")
                if new_body != (row["bodyMd"] or ""):
                    conn.execute(f"UPDATE {table} SET bodyMd = ? WHERE id = ?", (new_body, row["id"]))
                    changed += 1
    return changed


def redact_tool_messages(markers: tuple[str, ...], replacement: str) -> int:
    """Replaces the content of stored tool results that contain any of `markers` -- a tool result
    is machine output fed to the model, so swapping it keeps the conversation's tool-call pairing
    intact while removing what it carried. Returns how many messages changed."""
    changed = 0
    with _conn() as conn:
        for marker in markers:
            cursor = conn.execute(
                "UPDATE chatMessages SET content = ? WHERE role = 'tool' AND instr(content, ?) > 0",
                (replacement, marker),
            )
            changed += cursor.rowcount
    return changed


def update_settings(patch: dict) -> dict:
    merged = {**get_settings(), **patch}
    with _conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SETTINGS_KEY, json.dumps(merged, ensure_ascii=False)),
        )
    return merged
