"""Reads the Cloudflare API (read-only token) for the reachability chapter: which hostnames of one
zone point where (DNS), whether the tunnels are connected, and whether a WAF rule demands a client
certificate (mTLS) for a hostname.

Read-only (ADR-0014): every call is a GET against a fixed path below, scoped to one zone id and
(optionally) one account id that the credential carries -- so the token needs only Zone DNS:Read,
Zone WAF:Read and Account Cloudflare Tunnel:Read, restricted to that zone. The tunnel token endpoint
(`.../token`) is deliberately never called, and the API token never appears in a URL or error text.

Credential mapping: `url` = zone id, `username` = account id (optional; without it tunnels are not
read), `secretEnc` = the API token. Opt-in per credential (`allowProbe`) and per switch
(`scanEnableCloudflare`, default off, because this is a contact outside the LAN).

Only structured, non-secret fields leave this module (`cf_dns`, `cf_tunnel`, `cf_waf_mtls` facts).
"""
from __future__ import annotations

import re

import httpx

API = "https://api.cloudflare.com/client/v4"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_ID = re.compile(r"^[0-9a-f]{32}$")
HOSTNAME = re.compile(r"^(\*\.)?([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")
_MAX_PAGES = 20
_PER_PAGE = 50  # the rulesets endpoint answers HTTP 400 above 50; the same size works for all paths
_HOST_IN_EXPR = re.compile(r'http\.host\s+(?:eq\s+"([^"]+)"|in\s+\{([^}]*)\})')


def clean_host(value: object) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    return host if len(host) <= 253 and HOSTNAME.match(host) else ""


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    response = await client.get(f"{API}{path}", params=params)
    if response.status_code in (401, 403):
        raise PermissionError(f"HTTP {response.status_code}")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("success", True):
        raise ValueError("Unerwartete Antwort.")
    return data


async def _paged(client: httpx.AsyncClient, path: str, extra: dict | None = None) -> list[dict]:
    items: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        data = await _get(client, path, {"page": page, "per_page": _PER_PAGE, **(extra or {})})
        result = data.get("result")
        items += [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []
        info = data.get("result_info") or {}
        if page >= int(info.get("total_pages") or 1):
            break
    return items


def _dns_facts(records: list[dict]) -> list[dict]:
    facts = []
    for rec in records:
        host, kind = clean_host(rec.get("name")), str(rec.get("type") or "")
        if not host or kind not in ("A", "AAAA", "CNAME"):
            continue
        facts.append({"kind": "cf_dns", "key": f"{host}/{kind}", "data": {
            "host": host, "type": kind, "target": str(rec.get("content") or "")[:255],
            "proxied": bool(rec.get("proxied")), "provider": ""}})
    return facts


def _tunnel_facts(tunnels: list[dict]) -> list[dict]:
    facts = []
    for t in tunnels:
        tid = str(t.get("id") or "")
        if not tid or t.get("deleted_at"):
            continue
        facts.append({"kind": "cf_tunnel", "key": tid, "data": {
            "id": tid[:36], "name": str(t.get("name") or "")[:100], "status": str(t.get("status") or "")[:20]}})
    return facts


def _waf_hosts(expression: str) -> list[str]:
    """Hostnames of a rule that checks for a client certificate; only the expression is read."""
    if "cf.tls_client_auth" not in expression:
        return []
    hosts: list[str] = []
    for single, group in _HOST_IN_EXPR.findall(expression):
        for name in ([single] if single else re.findall(r'"([^"]+)"', group)):
            if clean_host(name) and clean_host(name) not in hosts:
                hosts.append(clean_host(name))
    return hosts


async def _waf_facts(client: httpx.AsyncClient, zone: str) -> list[dict]:
    facts: list[dict] = []
    for ruleset in await _paged(client, f"/zones/{zone}/rulesets"):
        rid = str(ruleset.get("id") or "")
        if ruleset.get("phase") != "http_request_firewall_custom" or not _ID.match(rid):
            continue
        detail = (await _get(client, f"/zones/{zone}/rulesets/{rid}")).get("result") or {}
        for rule in detail.get("rules") or []:
            for host in _waf_hosts(str((rule or {}).get("expression") or "")):
                facts.append({"kind": "cf_waf_mtls", "key": host, "data": {"host": host}})
    return facts


async def probe(zone_id: str, account_id: str, token: str) -> dict:
    """Returns {"ok", "error", "facts": [{kind, key, data}], "warnings": [str]}.

    Tunnel and WAF reads are optional, but a failed one is reported: without it, "no mTLS rule" and
    "could not read the rules" would look the same in the documentation.
    """
    warnings: list[str] = []
    zone_id, account_id = (zone_id or "").strip().lower(), (account_id or "").strip().lower()
    if not _ID.match(zone_id):
        return {"ok": False, "facts": [], "error": "Zone-ID fehlt oder ist ungültig (32 Hex-Zeichen im Feld Adresse)."}
    if account_id and not _ID.match(account_id):
        return {"ok": False, "facts": [], "error": "Account-ID ist ungültig (32 Hex-Zeichen im Feld Benutzername)."}
    if not token:
        return {"ok": False, "facts": [], "error": "API-Token fehlt."}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"Authorization": f"Bearer {token}"}) as client:
            facts = _dns_facts(await _paged(client, f"/zones/{zone_id}/dns_records"))
            if account_id:
                try:
                    facts += _tunnel_facts(await _paged(client, f"/accounts/{account_id}/cfd_tunnel",
                                                        {"is_deleted": "false"}))
                except (httpx.HTTPError, ValueError, PermissionError) as exc:
                    # tunnel status is optional; DNS alone still answers the main question
                    warnings.append(f"Tunnel-Status nicht lesbar ({type(exc).__name__}).")
            try:
                facts += await _waf_facts(client, zone_id)
            except (httpx.HTTPError, ValueError, PermissionError) as exc:
                warnings.append(f"WAF-Regeln nicht lesbar, mTLS unbekannt ({type(exc).__name__}).")
    except PermissionError:
        return {"ok": False, "facts": [], "error": "Cloudflare hat den Token abgelehnt – Token und Zone prüfen."}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "facts": [], "error": f"Cloudflare antwortete mit HTTP {exc.response.status_code}."}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "facts": [], "error": f"Cloudflare nicht erreichbar ({type(exc).__name__})."}
    return {"ok": True, "error": "", "facts": facts, "warnings": warnings}
