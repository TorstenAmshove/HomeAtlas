"""Reads port forwards and the WAN address from the classic UniFi Network API (ADR-0016).

The official integration API (`unifi_probe.py`) lists WANs with id and name only and has no port
forwards, so this module reads them from the classic API under ``/proxy/network/api``. The same
integration API key (header ``X-API-Key``) is accepted there (spike on UniFi Network 11.0.103), so
there is no login, no cookie, no CSRF token and no local user: every request is a GET against one of
three fixed paths (sites, ``rest/portforward``, ``stat/health``), redirects are not followed. Note the
trade-off recorded in ADR-0016: the key has the rights of whoever created it.

Opt-in like every source: only accounts of category ``unifi`` with ``allowProbe`` are used
(pipeline.py, the same accounts as `unifi_probe.py`), and only while ``scanEnableUnifiClassic`` is
on. The key never leaves this module (not in errors, not in results), and error texts never contain a
response body. This module must not import `unifi_live.py` (ADR-0015 keeps the scan separate); the
small GET helper is duplicated on purpose.

The WAN addresses are returned as plain list (`wanIps`); the pipeline attaches them to the WAN
resources `unifi_probe.py` already created, so there is one WAN row per connection.
"""
from __future__ import annotations

import ipaddress
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SITE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_FORWARDS = 500
_PORT = re.compile(r"^\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*$")


_KEY = re.compile(r"^[\x21-\x7e]{8,512}$")


async def _get_data(client: httpx.AsyncClient, base: str, path: str) -> list[dict]:
    response = await client.get(f"{base}{path}")
    status = response.status_code
    if status in (401, 403):
        raise PermissionError("UniFi API-Key abgelehnt oder ohne Rechte für die klassische API.")
    if status in (400, 404):
        raise ValueError("Endpunkt der klassischen UniFi-API nicht verfügbar (UniFi-Version?).")
    if 300 <= status < 400:
        raise ValueError("Unerwartete Weiterleitung der klassischen UniFi-API.")
    if status != 200:
        raise ValueError(f"Klassische UniFi-API antwortete mit Status {status}.")
    try:
        body = response.json()
    except ValueError:
        raise ValueError("Unerwartete Antwort der klassischen UniFi-API (kein JSON).") from None
    data = body.get("data") if isinstance(body, dict) else None
    meta = body.get("meta") if isinstance(body, dict) else None
    if isinstance(meta, dict) and meta.get("rc") == "error":
        raise ValueError("Klassische UniFi-API meldete einen Fehler.")
    if not isinstance(data, list):
        raise ValueError("Unerwartete Antwort der klassischen UniFi-API (keine Ergebnisliste).")
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


async def probe(base_url: str, api_key: str, account_id: str,
                controller_system_id: str | None) -> dict:
    """`{ok, error, forwards: [{kind, key, data}], wanIps: [str]}`; read-only, API key only."""
    fail = {"ok": False, "forwards": [], "wanIps": []}
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {**fail, "error": "Keine Adresse für die klassische UniFi-API hinterlegt."}
    if not api_key:
        return {**fail, "error": "Der UniFi API-Key fehlt."}
    if not _KEY.match(api_key):
        return {**fail, "error": "Ungültiger UniFi API-Key (Leerzeichen oder Zeilenumbruch?)."}
    forwards: list[dict] = []
    wan_ips: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, follow_redirects=False,
                                     headers={"X-API-Key": api_key}) as client:
            api = f"{base}/proxy/network/api"
            sites = [s for s in await _get_data(client, api, "/self/sites")
                     if _SITE_NAME.match(str(s.get("name") or ""))]
            for site in sites:
                name = site["name"]
                for entry in await _get_data(client, api, f"/s/{name}/rest/portforward"):
                    if (fwd := _forward(entry)) is not None and len(forwards) < _MAX_FORWARDS:
                        key = f"{name}:{fwd['proto']}:{fwd['wanPort']}>{fwd['destIp']}:{fwd['destPort']}"
                        forwards.append({"kind": "portforward", "key": key, "data": fwd})
                health = await _get_data(client, api, f"/s/{name}/stat/health")
                wan_ips += [_ip(h.get("wan_ip")) for h in health if h.get("subsystem") == "wan"]
    except PermissionError as exc:
        return {**fail, "error": str(exc)}
    except ValueError as exc:  # fixed German texts from _get_data only
        return {**fail, "error": str(exc)}
    except httpx.HTTPError as exc:
        return {**fail, "error": f"Klassische UniFi-API nicht lesbar: {type(exc).__name__}"}
    forwards.append({"kind": "portforward_scan", "key": "scan", "data": {"count": len(forwards)}})
    return {"ok": True, "error": "", "forwards": forwards, "wanIps": wan_ips}
