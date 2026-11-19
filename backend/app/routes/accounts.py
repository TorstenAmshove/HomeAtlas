"""Stored credentials (accounts) and their assignments. Secrets leave only one at a time via
`GET /api/accounts/{id}/secret`, admin-only and logged.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import crypto, db
from ..deps import _client, _public_account, current_user, require_admin

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------------------------

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


class NetworkResourceManualBody(BaseModel):
    manualMd: str = ""


@router.get("/api/network-resources")
async def list_network_resources(kind: str | None = None, activeOnly: bool = False,
                                 _: dict = Depends(current_user)) -> dict:
    return {"resources": db.list_network_resources(kind=kind, active_only=activeOnly)}


@router.patch("/api/network-resources/{resource_id}")
async def update_network_resource(resource_id: str, body: NetworkResourceManualBody,
                                  _: dict = Depends(require_admin)) -> dict:
    resource = db.update_network_resource_manual(resource_id, body.manualMd)
    if resource is None:
        raise HTTPException(status_code=404, detail="Netzwerkressource nicht gefunden.")
    return {"resource": resource}


@router.get("/api/accounts")
async def list_accounts(_: dict = Depends(require_admin)) -> dict:
    assignment_counts = db.count_assignments_by_account()
    return {"accounts": [
        {**_public_account(a), "assignmentCount": assignment_counts.get(a["id"], 0)}
        for a in db.list_accounts()
    ]}


@router.post("/api/accounts")
async def create_account(body: AccountBody, _: dict = Depends(require_admin)) -> dict:
    account = db.create_account({**body.model_dump(exclude={"secret", "passphrase"}),
                                 "secretEnc": crypto.encrypt(body.secret),
                                 "passphraseEnc": crypto.encrypt(body.passphrase)})
    return {"account": _public_account(account)}


@router.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, body: AccountBody, _: dict = Depends(require_admin)) -> dict:
    # Only the fields the client actually sent (#47): a partial body must not reset the others --
    # least of all `allowProbe`, the opt-in that decides whether a credential is used at all.
    patch = body.model_dump(exclude={"secret", "passphrase"}, exclude_unset=True)
    # An empty secret means "leave it alone" -- the edit form never receives the stored value, so
    # treating blank as "clear it" would silently delete the password on every unrelated edit.
    if body.secret:
        patch["secretEnc"] = crypto.encrypt(body.secret)
    if body.passphrase:
        patch["passphraseEnc"] = crypto.encrypt(body.passphrase)
    account = db.update_account(account_id, patch)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    return {"account": _public_account(account)}


@router.get("/api/accounts/{account_id}/secret")
async def reveal_secret(account_id: str, request: Request, user: dict = Depends(require_admin)) -> dict:
    account = db.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden.")
    ip, agent = _client(request)
    # Logged deliberately: for a credential store, "who looked at the router password, and when"
    # is the single most useful entry the log can hold.
    db.log_access("secret.reveal", user=user, ip=ip, user_agent=agent, detail=account["label"])
    return {"secret": crypto.decrypt(account["secretEnc"])}


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, _: dict = Depends(require_admin)) -> dict:
    db.delete_account(account_id)
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
