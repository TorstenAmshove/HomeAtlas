"""Reads the API of an internal Traefik (HTTP BasicAuth) for the services reachable internally
over TLS: router rule `Host(...)` -> service URL, entrypoint, certificate resolver, middlewares.

Read-only (ADR-0014): every call is a GET against one of the three fixed paths below
(`/api/http/routers`, `/api/http/services`, `/api/entrypoints`). The middleware endpoint is
deliberately never called, because it is the one that can carry BasicAuth user hashes.

Opt-in per credential like every other source: only accounts of category "traefik" with
`allowProbe` are used (pipeline.py), and only while `scanEnableTraefik` is on. The account's
`username`/`secretEnc` are the BasicAuth user of the Traefik API entrypoint, `url` its base address.

Only structured, non-secret fields leave this module (`traefik_router` facts, see exposure.py).
The raw rule, raw API objects and response bodies are dropped; error texts never contain a response
body or the address as entered (it may carry credentials).
"""
from __future__ import annotations

import re

import httpx

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_PER_PAGE = 100
_MAX_PAGES = 50
_MAX_ROUTERS = 2000
_HOST_CALL = re.compile(r"(?<![A-Za-z])Host\(([^)]*)\)")
_QUOTED = re.compile(r"[`\"']([^`\"']+)[`\"']")


async def _get_list(client: httpx.AsyncClient, base_url: str, path: str, paged: bool = True) -> list[dict]:
    items: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        params = {"page": page, "per_page": _PER_PAGE} if paged else None
        response = await client.get(f"{base_url}{path}", params=params)
        if response.status_code in (401, 403):
            raise PermissionError(f"HTTP {response.status_code}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unerwartete Antwort (keine Liste).")
        items += [d for d in data if isinstance(d, dict)]
        nxt = response.headers.get("X-Next-Page", "") if paged else ""
        if not nxt.isdigit() or int(nxt) <= page or len(items) >= _MAX_ROUTERS:
            break
        page = int(nxt)
    return items[:_MAX_ROUTERS]


def _hosts(rule: str) -> list[str]:
    hosts: list[str] = []
    for call in _HOST_CALL.findall(rule or ""):
        for name in _QUOTED.findall(call):
            name = name.strip().lower().rstrip(".")[:253]
            if name and name not in hosts:
                hosts.append(name)
    return hosts


def _service_urls(services: list[dict]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for svc in services:
        servers = (svc.get("loadBalancer") or {}).get("servers") or []
        first = next((s.get("url") or s.get("address") or "" for s in servers if isinstance(s, dict)), "")
        name = str(svc.get("name") or "")
        if name and first:
            urls[name] = str(first)[:300]
            urls.setdefault(name.split("@", 1)[0], str(first)[:300])
    return urls


def _facts(routers: list[dict], services: list[dict], entrypoints: list[dict]) -> list[dict]:
    urls = _service_urls(services)
    addresses = {str(e.get("name")): str(e.get("address") or "") for e in entrypoints}
    facts = []
    for router in routers:
        name = str(router.get("name") or "")[:200]
        if not name:
            continue
        service = str(router.get("service") or "")
        tls = router.get("tls")
        entry = [f"{n}{addresses.get(n, '')}"[:60] for n in router.get("entryPoints") or []][:5]
        facts.append({"kind": "traefik_router", "key": name, "data": {
            "hosts": _hosts(str(router.get("rule") or ""))[:20],
            "service": urls.get(service) or urls.get(service.split("@", 1)[0], ""),
            "resolver": str((tls or {}).get("certResolver") or "")[:100] if isinstance(tls, dict) else "",
            "middlewares": [str(m)[:100] for m in router.get("middlewares") or []][:20],
            "tls": bool(tls),
            "entrypoints": entry,
        }})
    return facts


async def probe(base_url: str, username: str, password: str) -> dict:
    """Returns {"ok", "error", "facts": [{kind, key, data}]}."""
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        return {"ok": False, "error": "Keine Adresse für Traefik hinterlegt.", "facts": []}
    if not username or not password:
        return {"ok": False, "error": "Benutzername oder Passwort fehlt.", "facts": []}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False,
                                     auth=httpx.BasicAuth(username, password)) as client:
            routers = await _get_list(client, base_url, "/api/http/routers")
            try:
                services = await _get_list(client, base_url, "/api/http/services")
            except (httpx.HTTPError, ValueError, PermissionError):
                services = []  # routers alone are still useful; targets stay empty
            try:
                entrypoints = await _get_list(client, base_url, "/api/entrypoints", paged=False)
            except (httpx.HTTPError, ValueError, PermissionError):
                entrypoints = []
    except PermissionError:
        return {"ok": False, "facts": [], "error": (
            "Traefik hat die hinterlegten Zugangsdaten abgelehnt – BasicAuth-Benutzer/Passwort prüfen.")}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "facts": [], "error": f"Traefik antwortete mit HTTP {exc.response.status_code}."}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "facts": [], "error": f"Traefik nicht erreichbar ({type(exc).__name__})."}
    return {"ok": True, "error": "", "facts": _facts(routers, services, entrypoints)}
