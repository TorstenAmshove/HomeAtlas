"""Reads port forwards and the WAN address from the classic UniFi Network API (ADR-0014).

The official integration API (`unifi_probe.py`) lists WANs with id and name only and has no port
forwards, so this module is the fallback. The classic API needs a login: the single POST of this
module is ``/api/auth/login`` (authentication only, no configuration is ever written). Everything
after that is a GET against one of three fixed paths (sites, ``rest/portforward``, ``stat/health``).
Use a dedicated local user with the role "View Only".

Opt-in like every source: only accounts of category ``unifi_classic`` with ``allowProbe`` are used
(pipeline.py), and only while ``scanEnableUnifiClassic`` is on. ``username``/``secretEnc`` are the
local user, ``url`` the console address. No password, cookie or CSRF token leaves this module, and
error texts never contain a response body.
"""
from __future__ import annotations

import ipaddress
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SITE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_FORWARDS = 500
_PORT = re.compile(r"^\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*$")


async def _get_data(client: httpx.AsyncClient, base: str, path: str) -> list[dict]:
    response = await client.get(f"{base}{path}")
    if response.status_code in (401, 403):
        raise PermissionError("Anmeldung an der klassischen UniFi-API abgelehnt.")
    response.raise_for_status()
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ValueError("Unerwartete Antwort (keine Ergebnisliste).")
    return [d for d in data if isinstance(d, dict)]


def _port(value: object) -> str:
    text = str(value or "").strip().replace(" ", "")
    return text if _PORT.match(text) else ""


def _ip(value: object) -> str:
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        return ""


def _forward(entry: dict) -> dict | None:
    """Only proto, ports, destination and the enabled flag; name, source filter etc. are dropped."""
    dest, wan_port, dest_port = _ip(entry.get("fwd")), _port(entry.get("dst_port")), _port(entry.get("fwd_port"))
    if not dest or not wan_port or not dest_port:
        return None
    proto = str(entry.get("proto") or "tcp_udp").lower()
    proto = {"tcp_udp": "TCP/UDP", "tcp": "TCP", "udp": "UDP"}.get(proto, "TCP/UDP")
    return {"proto": proto, "wanPort": wan_port, "destIp": dest, "destPort": dest_port,
            "enabled": bool(entry.get("enabled", True))}


async def probe(base_url: str, username: str, password: str, account_id: str,
                controller_system_id: str | None) -> dict:
    """`{ok, error, forwards: [{kind, key, data}], wan: [resource...], completeScopes}`."""
    fail = {"ok": False, "forwards": [], "resources": [], "completeScopes": []}
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {**fail, "error": "Keine Adresse für die klassische UniFi-API hinterlegt."}
    if not username or not password:
        return {**fail, "error": "Benutzername oder Passwort für die klassische UniFi-API fehlt."}
    forwards: list[dict] = []
    resources: list[dict] = []
    scopes: list[tuple[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            login = await client.post(f"{base}/api/auth/login",
                                      json={"username": username, "password": password, "remember": False})
            if login.status_code in (400, 401, 403):
                return {**fail, "error": "Anmeldung an der klassischen UniFi-API abgelehnt."}
            login.raise_for_status()
            csrf = login.headers.get("X-CSRF-Token")
            if csrf:
                client.headers["X-CSRF-Token"] = csrf
            api = f"{base}/proxy/network/api"
            sites = [s for s in await _get_data(client, api, "/self/sites")
                     if _SITE_NAME.match(str(s.get("name") or ""))]
            for site in sites:
                name = site["name"]
                label = str(site.get("desc") or name)[:100]
                for entry in await _get_data(client, api, f"/s/{name}/rest/portforward"):
                    if (fwd := _forward(entry)) is not None and len(forwards) < _MAX_FORWARDS:
                        key = f"{name}:{fwd['proto']}:{fwd['wanPort']}>{fwd['destIp']}:{fwd['destPort']}"
                        forwards.append({"kind": "portforward", "key": key, "data": fwd})
                health = await _get_data(client, api, f"/s/{name}/stat/health")
                for index, wan in enumerate(h for h in health if h.get("subsystem") == "wan"):
                    ip = _ip(wan.get("wan_ip"))
                    resources.append({
                        "kind": "wan", "source": "unifi", "siteExternalId": name, "siteName": label,
                        "externalId": f"wan{index + 1}", "name": f"Internet {index + 1}", "enabled": True,
                        "ownerSystemId": controller_system_id, "facts": {"ip": ip} if ip else {},
                    })
                scopes.append((name, "wan"))
    except PermissionError as exc:
        return {**fail, "error": str(exc)}
    except (httpx.HTTPError, ValueError) as exc:
        return {**fail, "error": f"Klassische UniFi-API nicht lesbar: {type(exc).__name__}"}
    forwards.append({"kind": "portforward_scan", "key": "scan", "data": {"count": len(forwards)}})
    return {"ok": True, "error": "", "forwards": forwards, "resources": resources, "completeScopes": scopes}
