"""Settings, release version (Über tab), LLM provider test/model refresh, OUI refresh, MCP access tokens, and the
one-time startup migration of secrets older versions stored readably.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, crypto, db, docker_probe, docs, llm_providers, model_catalog, oui, probe_auth
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


def _mask_settings(settings: dict) -> dict:
    masked = dict(settings)
    for field in _SECRET_SETTING_FIELDS:
        masked[field] = _MASK if settings.get(field) else ""
    for plain, encrypted in _ENCRYPTED_SETTING_FIELDS.items():
        # The ciphertext never leaves the server; the UI only learns whether something is stored.
        masked.pop(encrypted, None)
        masked[f"has{plain[0].upper()}{plain[1:]}"] = bool(settings.get(encrypted))
    return masked


def _unmask_patch(patch: dict, current: dict) -> dict:
    """The UI round-trips the masked value when the user edits an unrelated field; writing it back
    verbatim would replace the real key with asterisks."""
    cleaned = dict(patch)
    for field in _SECRET_SETTING_FIELDS:
        if field not in cleaned:
            continue
        if cleaned[field] == _MASK:
            cleaned[field] = current.get(field, "")
        elif cleaned[field]:
            # API keys are stored encrypted like every other credential (ADR-0007); only
            # llm_providers.api_key_for decrypts them, at the moment a request needs one.
            cleaned[field] = crypto.encrypt(str(cleaned[field]))
    for plain, encrypted in _ENCRYPTED_SETTING_FIELDS.items():
        if plain in cleaned:
            value = cleaned.pop(plain)
            # Blank means "leave it alone" -- the form never receives the stored value, so treating
            # it as "clear" would wipe the credential on every unrelated settings save.
            if value:
                cleaned[encrypted] = crypto.encrypt(value)
        cleaned.pop(f"has{plain[0].upper()}{plain[1:]}", None)
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
async def update_settings(patch: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    current = db.get_settings()
    merged = db.update_settings(_unmask_patch(patch, current))
    return {"settings": _mask_settings(merged)}


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
    if ok:
        cache = dict(db.get_settings().get("providerModelCache") or {})
        cache[provider] = {"models": models}
        db.update_settings({"providerModelCache": cache})
    return {"ok": ok, "message": message, "models": models}


@router.post("/api/settings/oui/refresh")
async def refresh_oui(_: dict = Depends(require_admin)) -> dict:
    ok, message = await oui.refresh_from_ieee()
    return {"ok": ok, "message": message, "entries": oui.entry_count()}
