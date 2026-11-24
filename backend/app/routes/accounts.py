"""Stored credentials (accounts) and their assignments. Secrets leave only one at a time via
`GET /api/accounts/{id}/secret`, admin-only and logged.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .. import crypto, db
from ..deps import _client, _public_account, current_user, require_admin

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------------------------

# Mirrors CATEGORIES in frontend/src/pages/zugaenge/categories.ts: a category the UI does not offer
# has no form and no meaning (a stray `router` once reached the TR-064 and reboot paths, #134).
ACCOUNT_CATEGORIES = frozenset({
    "contract", "login", "sshkey", "unifi", "homeassistant", "proxmox",
    "traefik", "cloudflare", "exposure_cloudflared", "exposure_caddy", "exposure_ddclient",
    "firewall_nftables", "wifi", "apikey", "other",
})


class AccountBody(BaseModel):
    systemId: str | None = None
    label: str = "Zugang"
    category: str = "login"
    username: str = ""
    secret: str = ""
    passphrase: str = ""
    url: str = ""
    notes: str = ""
    allowProbe: bool = False
    port: int = 0

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in ACCOUNT_CATEGORIES:
            raise ValueError(f"Unbekannte Kategorie: {value}")
        return value


class AccountPatchBody(AccountBody):
    """PATCH body: like `AccountBody`, plus an explicit way to empty a stored secret (same
    semantics as `clearSecrets` in PATCH /api/settings). A blank `secret` alone still means
    "unchanged"."""
    clearSecrets: list[Literal["secret", "passphrase"]] | None = None


def _require_system(system_id: str | None) -> None:
    if system_id and db.get_system(system_id) is None:
        raise HTTPException(status_code=422, detail="Gerät nicht gefunden.")


class NetworkResourceManualBody(BaseModel):
    manualMd: str = Field("", max_length=2000)


# Field -> German word for the `account.update` log detail. Only names ever reach the log, never values.
_FIELD_LABEL = {
    "secretEnc": "Passwort", "passphraseEnc": "Passphrase", "username": "Benutzername",
    "label": "Bezeichnung", "category": "Kategorie", "systemId": "Gerät", "url": "URL",
    "notes": "Notiz", "allowProbe": "Scan-Freigabe", "port": "Port",
}


@router.get("/api/network-resources")
async def list_network_resources(kind: str | None = None, activeOnly: bool = False,
                                 _: dict = Depends(current_user)) -> dict:
    return {"resources": db.list_network_resources(kind=kind, active_only=activeOnly)}


@router.patch("/api/network-resources/{resource_id}")
async def update_network_resource(resource_id: str, body: NetworkResourceManualBody,
                                  request: Request, admin: dict = Depends(require_admin)) -> dict:
    resource = db.update_network_resource_manual(resource_id, body.manualMd)
    if resource is None:
        raise HTTPException(status_code=404, detail="Netzwerkressource nicht gefunden.")
    ip, agent = _client(request)
    # Name only, not the note text: free text, and the assistant merely reads it.
    db.log_access("networkresource.update", user=admin, ip=ip, user_agent=agent,
                  detail=resource["name"])
    return {"resource": resource}


@router.get("/api/accounts")
async def list_accounts(_: dict = Depends(require_admin)) -> dict:
    assignment_counts = db.count_assignments_by_account()
    return {"accounts": [
        {**_public_account(a), "assignmentCount": assignment_counts.get(a["id"], 0)}
        for a in db.list_accounts()
    ]}


@router.post("/api/accounts")
async def create_account(body: AccountBody, request: Request,
                         admin: dict = Depends(require_admin)) -> dict:
    _require_system(body.systemId)
    account = db.create_account({**body.model_dump(exclude={"secret", "passphrase"}),
                                 "secretEnc": crypto.encrypt(body.secret),
                                 "passphraseEnc": crypto.encrypt(body.passphrase)})
    ip, agent = _client(request)
    db.log_access("account.create", user=admin, ip=ip, user_agent=agent, detail=account["label"])
    return {"account": _public_account(account)}


@router.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, body: AccountPatchBody, request: Request,
                         admin: dict = Depends(require_admin)) -> dict:
    # Only the fields the client actually sent (#47): a partial body must not reset the others --
    # least of all `allowProbe`, the opt-in that decides whether a credential is used at all.
    patch = body.model_dump(exclude={"secret", "passphrase", "clearSecrets"},
                            exclude_unset=True)
    # An empty secret means "leave it alone" -- the edit form never receives the stored value, so
    # treating blank as "clear it" would silently delete the password on every unrelated edit.
    if body.secret:
        patch["secretEnc"] = crypto.encrypt(body.secret)
    if body.passphrase:
        patch["passphraseEnc"] = crypto.encrypt(body.passphrase)
    cleared: list[str] = []
    for name in body.clearSecrets or []:
        if getattr(body, name):
            # Checked here, not in a pydantic validator: its 422 would echo the secret as `input`.
            raise HTTPException(status_code=422, detail=f"{name}: Entfernen und neuer Wert gleichzeitig.")
        patch[f"{name}Enc"] = crypto.encrypt("")
        cleared.append("Passwort entfernt" if name == "secret" else "Passphrase entfernt")
    if db.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    _require_system(patch.get("systemId"))
    account = db.update_account(account_id, patch)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    # Field names only -- a sent field counts as changed, same as the route itself.
    cleared_keys = {f"{n}Enc" for n in body.clearSecrets or []}
    fields = [_FIELD_LABEL[k] for k in patch if k in _FIELD_LABEL and k not in cleared_keys]
    fields += cleared
    if fields:
        ip, agent = _client(request)
        db.log_access("account.update", user=admin, ip=ip, user_agent=agent,
                      detail=f"{account['label']}: {', '.join(fields)}")
    return {"account": _public_account(account)}


@router.get("/api/accounts/{account_id}/secret")
async def reveal_secret(account_id: str, request: Request, user: dict = Depends(require_admin)) -> dict:
    account = db.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    ip, agent = _client(request)
    # Logged deliberately: for a credential store, "who looked at the router password, and when"
    # is the single most useful entry the log can hold.
    try:
        secret = crypto.decrypt_strict(account["secretEnc"])
    except crypto.SecretUnreadable as exc:
        db.log_access("secret.reveal", user=user, ip=ip, user_agent=agent, detail=account["label"], ok=False)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.log_access("secret.reveal", user=user, ip=ip, user_agent=agent, detail=account["label"])
    return {"secret": secret}


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, request: Request,
                         admin: dict = Depends(require_admin)) -> dict:
    account = db.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    db.delete_account(account_id)
    ip, agent = _client(request)
    db.log_access("account.delete", user=admin, ip=ip, user_agent=agent, detail=account["label"])
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# Account (credential-profile) assignments -- lets one account additionally apply to a whole
# device kind or subnet, beyond the single system its own `systemId` points at. See
# db.list_probe_accounts for how a scan resolves these back to a concrete credential per device;
# no secret is ever part of an assignment row, so nothing here needs the same "never returned in
# plaintext" care the account routes above take.
# ---------------------------------------------------------------------------------------------

class AccountAssignmentBody(BaseModel):
    targetType: str
    targetValue: str


@router.get("/api/accounts/{account_id}/assignments")
async def list_account_assignments(account_id: str, _: dict = Depends(require_admin)) -> dict:
    if db.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    return {"assignments": db.list_account_assignments(account_id)}


@router.put("/api/accounts/{account_id}/assignments")
async def set_account_assignments(account_id: str, body: list[AccountAssignmentBody],
                                  _: dict = Depends(require_admin)) -> dict:
    if db.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    assignments = db.set_account_assignments(account_id, [b.model_dump() for b in body])
    return {"assignments": assignments}
