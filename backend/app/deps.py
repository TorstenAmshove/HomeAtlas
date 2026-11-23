"""Shared request plumbing and helpers used by more than one route module (moved out of
main.py unchanged): session/role dependencies, client identity, WebSocket auth and the
small helpers several route groups share. Importing nothing from routes/ keeps it a leaf."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, HTTPException, Request, WebSocket, status

from . import auth

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


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def _peer_ip(headers, client_host: str | None) -> str:
    """Client address for throttling and the access log. `X-Real-IP` is set by the nginx in front
    and only believed when the TCP peer is loopback (ADR-0003: nginx reaches the backend via
    127.0.0.1); from any other peer the header is attacker-controlled and the peer address wins.
    An empty or non-IP header also falls back to the peer."""
    if _is_loopback(client_host):
        forwarded = (headers.get("x-real-ip") or "").strip()
        try:
            return str(ipaddress.ip_address(forwarded)) if forwarded else client_host or ""
        except ValueError:
            return client_host or ""
    return client_host or ""


def _cookie_secure(request: Request) -> bool:
    """Whether the session cookie gets the `Secure` flag. `HOMEATLAS_COOKIE_SECURE` is read on
    every call: `always`/`never` force it, anything else (default `auto`) follows the
    `X-Forwarded-Proto` that nginx passes on (https -> Secure). Plain HTTP stays the default
    deployment, so a blanket `Secure` would lock everybody out there."""
    mode = os.environ.get("HOMEATLAS_COOKIE_SECURE", "auto").strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    return request.headers.get("x-forwarded-proto", "").strip().lower() == "https"


def _client(request: Request) -> tuple[str, str]:
    """Best-effort client identity for the access log (see `_peer_ip` for the trust rule)."""
    return _peer_ip(request.headers, request.client.host if request.client else None), \
        request.headers.get("user-agent", "")


def _ws_client(websocket: WebSocket) -> tuple[str, str]:
    return _peer_ip(websocket.headers, websocket.client.host if websocket.client else None), \
        websocket.headers.get("user-agent", "")


async def _ws_authenticate(websocket: WebSocket) -> dict | None:
    """Same bar as `current_user` (valid session, `totpEnabled`) plus the ADMIN role. Returns None
    (caller closes with code=1008) rather than raising -- `HTTPException` has no meaning once a
    WebSocket connection is being negotiated; there is no HTTP response left to attach it to.

    `Origin` is mandatory: browsers send it on every WebSocket handshake and nginx passes it
    through, so a missing or `null` Origin is refused. It is defense in depth on top of the
    `samesite="lax"` session cookie; the blast radius of getting this check wrong (an interactive
    root shell) is much larger than anywhere else this app's cookie-only trust model is used.

    Compares hostnames only, not ports: reverse proxies routinely normalize or drop the port from
    the Host header they forward (the bundled nginx's `$host` strips it even though the browser's
    Origin always includes a non-default one), so a port-exact comparison would reject legitimate
    same-origin connections."""
    origin = websocket.headers.get("origin", "")
    origin_host = urlsplit(origin).hostname or "" if origin else ""
    request_host = (websocket.headers.get("host", "") or "").split(":")[0]
    if not origin_host or not request_host or origin_host != request_host:
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
