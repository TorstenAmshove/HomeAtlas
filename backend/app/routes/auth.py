"""Login, logout, password, mandatory second factor (TOTP) and user management.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

import secrets as _secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import auth, crypto, db, security
from ..deps import _client, current_user, require_admin, session_user

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str
    totpCode: str = ""


@router.get("/api/health")
async def health() -> dict:
    settings = db.get_settings()
    # uiCalm sits here (not only in /api/settings) so the frontend knows which shell to render
    # before the first page, the same way it learns about setupCompleted.
    return {"status": "ok", "setupCompleted": settings.get("setupCompleted", False),
            "uiCalm": db.ui_calm(settings), "userCount": db.count_users()}


@router.post("/api/auth/login")
async def login(body: LoginBody, response: Response, request: Request) -> dict:
    ip, agent = _client(request)
    retry_after = security.login_throttle.retry_after(body.username, ip)
    if retry_after:
        db.log_access("login", username=body.username, ip=ip, user_agent=agent, ok=False,
                      detail="gesperrt nach zu vielen Fehlversuchen")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Fehlversuche. Bitte in {max(1, retry_after // 60)} Minuten erneut versuchen.",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        user = auth.verify_login(body.username, body.password, body.totpCode)
    except auth.MfaRequired as exc:
        if exc.wrong_code:
            security.login_throttle.record_failure(body.username, ip)
        db.log_access("login.mfa", username=body.username, ip=ip, user_agent=agent, ok=False,
                      detail="falscher Code" if exc.wrong_code else "Code angefordert")
        # 401 + a flag rather than 200: the credentials alone did not authenticate anything yet.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=("Der Code stimmt nicht oder ist abgelaufen. Bitte den aktuellen aus der App eingeben."
                    if exc.wrong_code else "Bitte zusätzlich den 6-stelligen Code aus deiner Authenticator-App eingeben."),
            headers={"X-HomeAtlas-MFA": "required"},
        ) from exc
    if user is None:
        security.login_throttle.record_failure(body.username, ip)
        db.log_access("login", username=body.username, ip=ip, user_agent=agent, ok=False,
                      detail="Benutzername oder Passwort falsch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Benutzername oder Passwort stimmt nicht.")
    security.login_throttle.record_success(body.username, ip)
    db.log_access("login", user=user, ip=ip, user_agent=agent,
                  detail="mit zweitem Faktor" if user.get("totpEnabled") else "")
    token = auth.create_session(user["id"])
    response.set_cookie(
        auth.SESSION_COOKIE_NAME, token, max_age=auth.SESSION_TTL_SECONDS,
        httponly=True, samesite="lax", path="/",
    )
    return {"user": db.get_user(user["id"])}


@router.post("/api/auth/logout")
async def logout(response: Response, homeatlas_session: str | None = Cookie(default=None)) -> dict:
    if homeatlas_session:
        auth.destroy_session(homeatlas_session)
    response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
async def me(user: dict = Depends(session_user)) -> dict:
    return {"user": user}


class PasswordBody(BaseModel):
    currentPassword: str
    # No length constraint here on purpose: `security.check_password` owns the policy and returns a
    # sentence the user can act on. A pydantic `min_length` would short-circuit that with a raw 422.
    newPassword: str


@router.post("/api/auth/password")
async def change_password(body: PasswordBody, request: Request, user: dict = Depends(current_user)) -> dict:
    ip, agent = _client(request)
    try:
        changed = auth.change_password(user["id"], body.currentPassword, body.newPassword)
    except security.PasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        db.log_access("password.change", user=user, ip=ip, user_agent=agent, ok=False,
                      detail="aktuelles Passwort falsch")
        raise HTTPException(status_code=400, detail="Das aktuelle Passwort stimmt nicht.")
    db.log_access("password.change", user=user, ip=ip, user_agent=agent)
    return {"ok": True}


@router.get("/api/auth/password-policy")
async def password_policy(_: dict = Depends(current_user)) -> dict:
    return security.describe_policy()


# ---------------------------------------------------------------------------------------------
# Second factor (TOTP) -- mandatory. `current_user` (see above) refuses every other route until
# `totpEnabled` is set, so `setup`/`confirm` below use the unenrolled-friendly `session_user`
# instead -- they are precisely the routes a not-yet-enrolled session must still reach. There is
# deliberately no self-service "disable": once required, turning it back off is an admin action
# (`reset_user_mfa` in the users section) so a stolen password alone can never strip it.
# ---------------------------------------------------------------------------------------------

class TotpBody(BaseModel):
    code: str = ""


@router.post("/api/auth/mfa/setup")
async def mfa_setup(user: dict = Depends(session_user)) -> dict:
    """Creates a fresh secret and hands back the QR. Not yet active -- `totpEnabled` only flips
    after `/confirm` proves a working code, so a half-finished setup can't lock anyone out."""
    if user.get("totpEnabled"):
        raise HTTPException(status_code=400, detail="Die Zwei-Faktor-Anmeldung ist bereits aktiv.")
    secret = security.generate_totp_secret()
    db.update_user(user["id"], {"totpSecretEnc": crypto.encrypt(secret), "totpEnabled": False})
    uri = security.provisioning_uri(secret, user["username"])
    return {"secret": secret, "uri": uri, "qrSvg": security.qr_svg(uri)}


@router.post("/api/auth/mfa/confirm")
async def mfa_confirm(body: TotpBody, request: Request, user: dict = Depends(session_user)) -> dict:
    raw = db.get_user_raw(user["id"]) or {}
    secret = crypto.decrypt(raw.get("totpSecretEnc") or "")
    if not secret:
        raise HTTPException(status_code=400, detail="Bitte zuerst die Einrichtung starten.")
    counter = security.totp_counter(secret, body.code)
    if counter is None or not db.claim_totp_counter(user["id"], counter):
        raise HTTPException(status_code=400, detail="Der Code stimmt nicht. Bitte den aktuellen aus der App eingeben.")
    db.update_user(user["id"], {"totpEnabled": True})
    ip, agent = _client(request)
    db.log_access("mfa.enable", user=user, ip=ip, user_agent=agent)
    return {"ok": True}


@router.get("/api/users")
async def list_users(_: dict = Depends(require_admin)) -> dict:
    return {"users": db.list_users()}


class UserBody(BaseModel):
    username: str = Field(min_length=1)
    password: str  # policy enforced in the route, see PasswordBody
    role: str = auth.ROLE_MEMBER
    displayName: str = ""


@router.post("/api/users")
async def create_user(body: UserBody, request: Request, admin: dict = Depends(require_admin)) -> dict:
    if db.get_user_by_username_raw(body.username) is not None:
        raise HTTPException(status_code=409, detail="Diesen Benutzernamen gibt es schon.")
    try:
        security.check_password(body.password, body.username)
    except security.PasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    role = body.role if body.role in (auth.ROLE_ADMIN, auth.ROLE_MEMBER) else auth.ROLE_MEMBER
    salt = _secrets.token_hex(16)
    user_id = db.create_user(body.username, auth.hash_password(body.password, salt), salt, role, body.displayName)
    ip, agent = _client(request)
    db.log_access("user.create", user=admin, ip=ip, user_agent=agent,
                  detail=f"{body.username} als {role}")
    return {"user": db.get_user(user_id)}


class UserPatchBody(BaseModel):
    displayName: str | None = None
    role: str | None = None
    newPassword: str | None = None


@router.patch("/api/users/{user_id}")
async def update_user(user_id: str, body: UserPatchBody, request: Request,
                      admin: dict = Depends(require_admin)) -> dict:
    target = db.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    patch: dict = {}
    changes: list[str] = []
    if body.displayName is not None and body.displayName != target["displayName"]:
        patch["displayName"] = body.displayName
        changes.append("Anzeigename")
    if body.role is not None and body.role != target["role"]:
        if body.role not in (auth.ROLE_ADMIN, auth.ROLE_MEMBER):
            raise HTTPException(status_code=400, detail="Unbekannte Rolle.")
        # Demoting the last admin would leave nobody able to reach settings or secrets, with no
        # recovery path short of editing the database by hand.
        admins = [u for u in db.list_users() if u["role"] == auth.ROLE_ADMIN]
        if target["role"] == auth.ROLE_ADMIN and body.role != auth.ROLE_ADMIN and len(admins) <= 1:
            raise HTTPException(status_code=400,
                                detail="Der letzte Administrator kann die Rolle nicht abgeben.")
        patch["role"] = body.role
        changes.append(f"Rolle → {body.role}")
    if patch:
        db.update_user(user_id, patch)

    if body.newPassword:
        try:
            security.check_password(body.newPassword, target["username"])
        except security.PasswordError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        auth.set_password(user_id, body.newPassword)
        # An open session would otherwise keep working with the replaced credential, which is not
        # what anyone means by "reset the password".
        db.invalidate_user_sessions(user_id)
        changes.append("Passwort zurückgesetzt, offene Sitzungen beendet")

    if changes:
        ip, agent = _client(request)
        db.log_access("user.update", user=admin, ip=ip, user_agent=agent,
                      detail=f"{target['username']}: {', '.join(changes)}")
    return {"user": db.get_user(user_id), "changes": changes}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)) -> dict:
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Das eigene Konto lässt sich nicht löschen.")
    admins = [u for u in db.list_users() if u["role"] == auth.ROLE_ADMIN]
    if len(admins) <= 1 and any(u["id"] == user_id for u in admins):
        # Otherwise the instance ends up with no one who can change settings or read secrets, and
        # there is no recovery path short of editing the database by hand.
        raise HTTPException(status_code=400, detail="Der letzte Administrator lässt sich nicht löschen.")
    db.delete_user(user_id)
    return {"ok": True}


@router.post("/api/users/{user_id}/mfa/reset")
async def reset_user_mfa(user_id: str, request: Request, admin: dict = Depends(require_admin)) -> dict:
    """The only way a second factor comes off an account -- see the module note above the TOTP
    routes. Clears it rather than disabling the requirement: `current_user` treats
    `totpEnabled = False` as "must enroll again", so this both recovers a locked-out user (lost
    phone, reinstalled app) and immediately ends any open session's access to everything except
    that enrollment, without waiting for it to expire."""
    target = db.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    db.update_user(user_id, {"totpSecretEnc": "", "totpEnabled": False})
    ip, agent = _client(request)
    db.log_access("mfa.reset", user=admin, ip=ip, user_agent=agent, detail=target["username"])
    return {"user": db.get_user(user_id)}
