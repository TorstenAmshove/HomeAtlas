"""Settings, release version (Über tab), LLM provider test/model refresh, OUI refresh, MCP access tokens, and the
one-time startup migration of secrets older versions stored readably.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, create_model, model_validator

from .. import auth, crypto, db, discovery, docker_probe, docs, llm_providers, model_catalog, oui, probe_auth
from ..deps import current_user, logger, require_admin
from ..version import app_version

router = APIRouter()


@router.get("/api/version")
def get_version(_user: dict = Depends(current_user)) -> dict:
    """Release version of the running backend, shown in Settings -> Über (any logged-in user)."""
    return {"version": app_version()}


# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------

_SECRET_SETTING_FIELDS = ("claudeApiKey", "openAiApiKey", "geminiApiKey", "deepseekApiKey", "ollamaApiKey")


# Written encrypted, never returned. The client sends plaintext under the name without the `Enc`
# suffix; an empty value means "keep what is stored", same rule as the account edit form.
_ENCRYPTED_SETTING_FIELDS = {
    "defaultCredentialSecret": "defaultCredentialSecretEnc",
    "defaultCredentialPassphrase": "defaultCredentialPassphraseEnc",
}


_MASK = "********"


def _migrate_plaintext_secrets() -> None:
    """One-time, idempotent clean-up at startup for data older versions stored readably:
    - LLM API keys in the settings blob are encrypted (ADR-0007),
    - config exports are removed from systems.extra.probe (they stay, encrypted, in
      deviceConfigVersions), and from already generated doc pages, page versions and stored
      assistant tool results that copied them from there."""
    settings = db.get_settings()
    plaintext = {f: crypto.encrypt(settings[f]) for f in _SECRET_SETTING_FIELDS
                 if settings.get(f) and not crypto.is_encrypted(settings[f])}
    if plaintext:
        db.update_settings(plaintext)
    stripped = db.strip_probe_facts(probe_auth.CONFIG_BACKUP_KEYS)
    scrubbed = db.rewrite_doc_bodies(docs.scrub_config_exports)
    redacted = db.redact_tool_messages(
        probe_auth.CONFIG_BACKUP_LABELS,
        json.dumps({"error": "Inhalt entfernt: enthielt einen Konfigurationsexport."}, ensure_ascii=False),
    )
    if plaintext or stripped or scrubbed or redacted:
        logger.warning(
            "HomeAtlas: Klartext-Secrets bereinigt: %d API-Schluessel verschluesselt, "
            "Konfigurationsexporte entfernt aus %d Geraeten, %d Doku-Staenden, %d Chat-Werkzeugergebnissen.",
            len(plaintext), stripped, scrubbed, redacted,
        )


_CLEARABLE = _SECRET_SETTING_FIELDS + tuple(_ENCRYPTED_SETTING_FIELDS)
_PROVIDERS = tuple(model_catalog.PROVIDER_LABELS)


def _has_flag(plain: str) -> str:
    return f"has{plain[0].upper()}{plain[1:]}"


# Read-only in the GET response: accepted in a PATCH body (the UI sends the whole form back) but
# dropped before saving. Raw `*Enc` fields are not known keys at all -> 422.
_READ_ONLY_FIELDS = ("setupCompleted", "providerModelCache") + tuple(_has_flag(p) for p in _ENCRYPTED_SETTING_FIELDS)


def _field_spec(name: str, default):
    if name == "llmProvider":
        return (Literal[_PROVIDERS], None)
    if isinstance(default, bool):
        return (StrictBool, None)
    if isinstance(default, int):
        return (StrictInt, Field(None, ge=0))
    if isinstance(default, str):
        return (StrictStr, None)
    if isinstance(default, list):
        return (list[StrictStr], None)
    return (dict, None)


def _patch_fields() -> dict:
    fields = {n: _field_spec(n, d) for n, d in db.DEFAULT_SETTINGS.items() if not n.endswith("Enc")}
    fields.update({p: (StrictStr, None) for p in _ENCRYPTED_SETTING_FIELDS})
    fields.update({_has_flag(p): (StrictBool, None) for p in _ENCRYPTED_SETTING_FIELDS})
    fields["clearSecrets"] = (list[Literal[_CLEARABLE]], None)
    return fields


class _SettingsPatchBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _no_clear_with_value(self):
        for name in self.clearSecrets or []:
            value = getattr(self, name, None)
            if value and value != _MASK:
                raise ValueError(f"{name}: Entfernen und neuer Wert gleichzeitig.")
        return self

    @model_validator(mode="after")
    def _valid_scan_subnets(self):
        if getattr(self, "scanSubnets", None) is not None:
            self.scanSubnets = discovery.validate_scan_subnets(self.scanSubnets)
        return self


# Built from DEFAULT_SETTINGS so a new setting is writable without a second list to keep in sync.
SettingsPatch = create_model("SettingsPatch", __base__=_SettingsPatchBase, **_patch_fields())


def _mask_settings(settings: dict) -> dict:
    # Only known keys: legacy keys stay in the DB but are not shown, so the UI's round trip of the
    # whole form can never send an unknown key back.
    masked = {k: v for k, v in settings.items() if k in db.DEFAULT_SETTINGS and not k.endswith("Enc")}
    for field in _SECRET_SETTING_FIELDS:
        masked[field] = _MASK if settings.get(field) else ""
    for plain, encrypted in _ENCRYPTED_SETTING_FIELDS.items():
        # The ciphertext never leaves the server; the UI only learns whether something is stored.
        masked[_has_flag(plain)] = bool(settings.get(encrypted))
    return masked


def _unmask_patch(patch: dict, current: dict) -> dict:
    """One rule for every secret: empty or the masked placeholder means "keep what is stored";
    removal goes only through `clearSecrets` (see update_settings). The UI round-trips the mask
    when the user edits an unrelated field."""
    cleaned = dict(patch)
    cleaned.pop("clearSecrets", None)
    for field in _SECRET_SETTING_FIELDS:
        if field not in cleaned:
            continue
        if cleaned[field] in ("", _MASK):
            del cleaned[field]
        else:
            # API keys are stored encrypted like every other credential (ADR-0007); only
            # llm_providers.api_key_for decrypts them, at the moment a request needs one.
            cleaned[field] = crypto.encrypt(str(cleaned[field]))
    for plain, encrypted in _ENCRYPTED_SETTING_FIELDS.items():
        if plain in cleaned:
            value = cleaned.pop(plain)
            if value and value != _MASK:
                cleaned[encrypted] = crypto.encrypt(value)
        cleaned.pop(_has_flag(plain), None)
    return cleaned


@router.get("/api/settings")
async def get_settings(user: dict = Depends(current_user)) -> dict:
    settings = _mask_settings(db.get_settings())
    if user["role"] != auth.ROLE_ADMIN:
        # A member has no business seeing which endpoints/models are configured.
        settings = {k: v for k, v in settings.items() if k in ("homeName", "setupCompleted")}
    return {"settings": settings, "providers": model_catalog.PROVIDER_LABELS,
            "catalog": {p: [vars(m) for m in model_catalog.options_for(p)] for p in model_catalog.PROVIDER_LABELS},
            "ouiLoaded": oui.is_downloaded(), "ouiEntries": oui.entry_count(),
            "dockerAvailable": docker_probe.socket_available()}


@router.patch("/api/settings")
async def update_settings(patch: SettingsPatch, _: dict = Depends(require_admin)) -> dict:  # type: ignore[valid-type]
    data = patch.model_dump(exclude_unset=True)
    for name in _READ_ONLY_FIELDS:
        if not name.startswith("has"):
            data.pop(name, None)
    cleared = data.get("clearSecrets") or []
    before = db.get_settings()
    cleaned = _unmask_patch(data, before)
    for name in cleared:
        cleaned[_ENCRYPTED_SETTING_FIELDS.get(name, name)] = ""
    merged = db.update_settings(cleaned)
    # A cached model list belongs to the key + server address it was fetched with.
    cache = dict(merged.get("providerModelCache") or {})
    stale = [p for p in cache if _connection_identity(p, before) != _connection_identity(p, merged)]
    if stale:
        for provider in stale:
            del cache[provider]
        merged = db.update_settings({"providerModelCache": cache})
    return {"settings": _mask_settings(merged)}


def _connection_identity(provider: str, settings: dict) -> tuple[str, str] | None:
    """(plaintext key, effective base URL) -- what a model list depends on. None when the stored key
    cannot be decrypted, which never compares equal to anything, so the cache is dropped."""
    try:
        return llm_providers.api_key_for(provider, settings), llm_providers.base_url_for(provider, settings)
    except llm_providers.ProviderError:
        return None


# ---------------------------------------------------------------------------------------------
# MCP access tokens (see mcp_server.py) -- admin-only, same "never bulk-return a secret" rule as
# accounts: list/create responses never carry a raw token except the one moment it's minted.
# ---------------------------------------------------------------------------------------------

class McpTokenBody(BaseModel):
    label: str


@router.get("/api/settings/mcp-tokens")
async def list_mcp_tokens(_: dict = Depends(require_admin)) -> dict:
    return {"tokens": db.list_api_tokens()}


@router.post("/api/settings/mcp-tokens")
async def create_mcp_token(body: McpTokenBody, _: dict = Depends(require_admin)) -> dict:
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="Bitte eine Bezeichnung angeben.")
    return {"token": db.create_api_token(body.label.strip())}


@router.delete("/api/settings/mcp-tokens/{token_id}")
async def delete_mcp_token(token_id: str, _: dict = Depends(require_admin)) -> dict:
    db.delete_api_token(token_id)
    return {"ok": True}


class ProviderBody(BaseModel):
    provider: str
    settings: dict = Field(default_factory=dict)


def _settings_for_provider_test(body: ProviderBody) -> tuple[str, dict]:
    """Test against the *unsaved* form state so an admin can verify a key before storing it, while
    still allowing the masked placeholder to mean "keep what's saved"."""
    stored = db.get_settings()
    return body.provider, {**stored, **_unmask_patch(body.settings, stored)}


@router.post("/api/settings/llm/test")
async def test_llm(body: ProviderBody, _: dict = Depends(require_admin)) -> dict:
    provider, settings = _settings_for_provider_test(body)
    ok, message, model = await llm_providers.test_connection(provider, settings)
    return {"ok": ok, "message": message, "model": model}


@router.post("/api/settings/llm/models")
async def refresh_llm_models(body: ProviderBody, _: dict = Depends(require_admin)) -> dict:
    provider, settings = _settings_for_provider_test(body)
    ok, message, models = await llm_providers.refresh_models(provider, settings)
    stored = db.get_settings()
    identity = _connection_identity(provider, settings)
    # An unsaved key/address would cache a list that belongs to values the server does not hold yet.
    persisted = ok and identity is not None and identity == _connection_identity(provider, stored)
    if persisted:
        cache = dict(stored.get("providerModelCache") or {})
        cache[provider] = {"models": models}
        db.update_settings({"providerModelCache": cache})
    elif ok:
        message += " Die Liste gilt bis zum Speichern; danach erneut laden."
    return {"ok": ok, "message": message, "models": models, "persisted": persisted}


@router.post("/api/settings/oui/refresh")
async def refresh_oui(_: dict = Depends(require_admin)) -> dict:
    ok, message = await oui.refresh_from_ieee()
    return {"ok": ok, "message": message, "entries": oui.entry_count()}
