"""Shared request plumbing and helpers used by more than one route module (moved out of
main.py unchanged): session/role dependencies, client identity, WebSocket auth and the
small helpers several route groups share. Importing nothing from routes/ keeps it a leaf."""
from __future__ import annotations

from __future__ import annotations
import asyncio
import logging
from fastapi import Cookie, Depends, HTTPException, Request, WebSocket, status
from . import (auth)



logger = logging.getLogger("homeatlas")


# Keeps background scan tasks referenced; without this the event loop may garbage-collect a
# running task and the scan silently stops mid-sweep.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------------------------
# Auth plumbing
# ---------------------------------------------------------------------------------------------

def session_user(homeatlas_session: str | None = Cookie(default=None)) -> dict:
    """Resolves the session without requiring MFA enrollment to already be complete. Used only by
    the handful of routes an unenrolled session must still be able to reach: `/me` (so the
    frontend can even tell it needs to show the enrollment screen), `/logout`, and the enrollment
    endpoints themselves. Everything else goes through `current_user` below."""
    user = auth.get_session_user(homeatlas_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    return user


def current_user(user: dict = Depends(session_user)) -> dict:
    """The second factor is mandatory, not optional: a session whose account has not enrolled one
    yet gets 403'd out of everything except the allowlist above until it does. This is the one
    place that rule lives -- every other route in this file depends on `current_user` (directly or
    via `require_admin`), so nothing has to remember to check it individually."""
    if not user.get("totpEnabled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bitte zuerst die Zwei-Faktor-Anmeldung einrichten.",
            headers={"X-HomeAtlas-MFA": "enrollment-required"},
        )
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != auth.ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Dafür werden Administratorrechte benötigt.")
    return user


def _client(request: Request) -> tuple[str, str]:
    """Best-effort client identity for the access log. `X-Real-IP` comes from the nginx in front;
    without it every entry would read 127.0.0.1 and the log would be useless."""
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    return ip, request.headers.get("user-agent", "")


def _ws_client(websocket: WebSocket) -> tuple[str, str]:
    ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "")
    return ip, websocket.headers.get("user-agent", "")


async def _ws_authenticate(websocket: WebSocket) -> dict | None:
    """Same bar as `current_user`: admin role AND `totpEnabled`. Returns None (caller closes with
    code=1008) rather than raising -- `HTTPException` has no meaning once a WebSocket connection
    is being negotiated; there is no HTTP response left to attach it to.

    A same-origin browser WebSocket handshake carries cookies automatically (confirmed: the
    session cookie is `samesite="lax"`, which permits same-site top-level navigation-adjacent
    requests including a same-origin WS upgrade, same as it already permits same-origin fetches).
    The `Origin` check below is defense in depth on top of that, not a response to a found gap --
    it costs nothing and the blast radius of getting this specific check wrong (an interactive
    root shell) is much larger than anywhere else this app's cookie-only trust model is used.

    Compares hostnames only, not ports: reverse proxies routinely normalize or drop the port from
    the Host header they forward (confirmed against this app's own bundled nginx -- its `$host`
    variable strips the port even though the browser's Origin always includes a non-default one),
    so a port-exact comparison would reject legitimate same-origin connections through any such
    proxy, not just catch cross-origin ones."""
    origin = websocket.headers.get("origin", "")
    if origin:
        from urllib.parse import urlsplit
        origin_host = urlsplit(origin).hostname or ""
        request_host = (websocket.headers.get("host", "") or "").split(":")[0]
        if not origin_host or origin_host != request_host:
            return None
    user = auth.get_session_user(websocket.cookies.get(auth.SESSION_COOKIE_NAME))
    if user is None or not user.get("totpEnabled") or user["role"] != auth.ROLE_ADMIN:
        return None
    return user


def _public_account(account: dict) -> dict:
    """Strips both encrypted blobs. `hasSecret`/`hasPassphrase` tell the UI whether something is
    stored without ever shipping it."""
    return {k: v for k, v in account.items() if k not in ("secretEnc", "passphraseEnc")} | {
        "hasSecret": bool(account.get("secretEnc")),
        "hasPassphrase": bool(account.get("passphraseEnc")),
    }
