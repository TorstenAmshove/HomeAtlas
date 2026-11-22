"""Reads the public address of a FRITZ!Box for the reachability chapter (ADR-0018).

Exactly one read-only SOAP action (`GetExternalIPAddress`) against one fixed IGD path. It needs no
credential, so none is sent; the account with `allowProbe` is only the opt-in. Redirects are not
followed, and neither the response body nor the box's address appears in an error text.

This source is optional: UniFi reports the public address on its own, so the scan keeps working
once the FRITZ!Box is gone.
"""
from __future__ import annotations

import ipaddress
import re

import httpx

_PORT = 49000
_PATH = "/igdupnp/control/WANIPConn1"
_SERVICE = "urn:schemas-upnp-org:service:WANIPConnection:1"
_TIMEOUT = httpx.Timeout(6.0, connect=3.0)
_ADDRESS = re.compile(r"<NewExternalIPAddress>\s*([0-9a-fA-F:.]{2,45})\s*</NewExternalIPAddress>")
_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
    f'<u:GetExternalIPAddress xmlns:u="{_SERVICE}" />'
    "</s:Body></s:Envelope>"
)


async def probe(host: str) -> dict:
    """`{ok, error, ip}`; `ip` is only ever a globally routable address."""
    fail = {"ok": False, "ip": ""}
    if not host:
        return {**fail, "error": "Keine Adresse für die FRITZ!Box hinterlegt."}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                f"http://{host}:{_PORT}{_PATH}", content=_ENVELOPE.encode(),
                headers={"Content-Type": 'text/xml; charset="utf-8"',
                         "SOAPAction": f"{_SERVICE}#GetExternalIPAddress"})
    except httpx.HTTPError as exc:
        return {**fail, "error": f"FRITZ!Box nicht erreichbar ({type(exc).__name__})."}
    if response.status_code != 200:
        return {**fail, "error": f"FRITZ!Box antwortete mit Status {response.status_code}."}
    match = _ADDRESS.search(response.text)
    try:
        address = ipaddress.ip_address(match.group(1)) if match else None
    except ValueError:
        address = None
    if address is None or not address.is_global:
        return {**fail, "error": "FRITZ!Box meldet keine öffentliche Adresse."}
    return {"ok": True, "error": "", "ip": str(address)}
