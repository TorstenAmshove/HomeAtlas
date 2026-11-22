"""Reads UniFi firewall zones, policies and address/port groups, read-only (ADR-0017).

Three fixed GET paths per site, all with the integration API key (header ``X-API-Key``, like
`unifi_classic_probe.py`; no login, no cookie, redirects are not followed):

- ``/proxy/network/v2/api/site/<site>/firewall/zone``      (plain JSON list)
- ``/proxy/network/v2/api/site/<site>/firewall-policies``  (plain JSON list)
- ``/proxy/network/api/s/<site>/rest/firewallgroup``       (``{"data": [...]}``)

The v2 group paths answer 404 on UniFi Network 11.0.103, so the classic path is used (spike, #106).
Opt-in like every source: only accounts of category ``unifi`` with ``allowProbe`` and only while
``scanEnableFirewallUnifi`` is on (pipeline.py). The key never leaves this module (not in errors, not
in results), error texts never contain a response body.

Only a positive list of fields is kept; raw answers are never stored. What the evaluation
(`firewall_eval.py`) cannot judge with certainty is recorded as ``unsupported`` reasons on the policy
(time schedule, IPsec match, "custom" connection states, negated matches, unknown action, formats
this module does not understand). The evaluation then reports "unclear" instead of guessing.

This module must not import `unifi_live.py` (ADR-0015/0017 keep the scan separate); the small GET
helper is duplicated on purpose. More than 500 policies makes the source unreadable (no subset: a
partial rule set would produce wrong verdicts).
"""
from __future__ import annotations

import ipaddress
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SITE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KEY = re.compile(r"^[\x21-\x7e]{8,512}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_PORTS = re.compile(r"^\d{1,5}(,\d{1,5})*$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_POLICIES = 500
_MAX_ZONES = 50
_MAX_GROUPS = 500
_MAX_MEMBERS = 500
_MAX_IPS = 200
_ACTIONS = {"ALLOW", "BLOCK"}
_PROTOCOLS = {"all", "tcp", "udp", "tcp_udp", "icmp", "icmpv6", "igmp"}
_IP_VERSIONS = {"BOTH", "IPV4", "IPV6"}
_STATES = {"ALL", "RESPOND_ONLY", "CUSTOM"}
_GROUP_TYPES = {"address-group", "port-group"}


class _Unreadable(Exception):
    """Fixed German text, safe to show (never contains a response body)."""


async def _get_json(client: httpx.AsyncClient, url: str) -> list[dict]:
    response = await client.get(url)
    status = response.status_code
    if status in (401, 403):
        raise _Unreadable("UniFi API-Key abgelehnt oder ohne Rechte für die Firewall-Regeln.")
    if status in (400, 404):
        raise _Unreadable("Firewall-Endpunkt der UniFi-API nicht verfügbar (UniFi-Version?).")
    if 300 <= status < 400:
        raise _Unreadable("Unerwartete Weiterleitung der UniFi-API.")
    if status != 200:
        raise _Unreadable(f"UniFi-API antwortete mit Status {status}.")
    try:
        body = response.json()
    except ValueError:
        raise _Unreadable("Unerwartete Antwort der UniFi-API (kein JSON).") from None
    if isinstance(body, dict):  # classic envelope {"meta": {...}, "data": [...]}
        meta = body.get("meta")
        if isinstance(meta, dict) and meta.get("rc") == "error":
            raise _Unreadable("UniFi-API meldete einen Fehler.")
        body = body.get("data")
    if not isinstance(body, list):
        raise _Unreadable("Unerwartete Antwort der UniFi-API (keine Ergebnisliste).")
    return [d for d in body if isinstance(d, dict)]


def _text(value: object, limit: int = 80) -> str:
    return _CONTROL.sub("", str(value or "")).strip()[:limit]


def _id(value: object) -> str:
    text = str(value or "")
    return text if _ID.match(text) else ""


def _ip_entry(value: object) -> str:
    """A single IP or an inclusive range ``a-b`` (IPv4 or IPv6 literal); anything else is ''."""
    text = str(value or "").strip()
    parts = text.split("-")
    try:
        if len(parts) == 1:
            return str(ipaddress.ip_address(parts[0]))
        if len(parts) == 2:
            first, last = ipaddress.ip_address(parts[0].strip()), ipaddress.ip_address(parts[1].strip())
            return f"{first}-{last}" if first.version == last.version and first <= last else ""
    except ValueError:
        return ""
    return ""


def _zone(entry: dict, site: str) -> dict | None:
    zone_id = _id(entry.get("_id"))
    if not zone_id:
        return None
    networks = [n for n in (_id(x) for x in (entry.get("network_ids") or [])
                            if isinstance(entry.get("network_ids"), list)) if n]
    return {"kind": "zone", "key": f"zone:{site}:{zone_id}", "data": {
        "site": site, "id": zone_id, "name": _text(entry.get("name")), "zoneKey": _text(entry.get("zone_key"), 40),
        "defaultZone": bool(entry.get("default_zone")), "networkIds": networks}}


def _side(entry: object, unsupported: list[str], label: str) -> dict:
    """Source or destination of a policy: only zone, target type, IPs/groups and ports."""
    entry = entry if isinstance(entry, dict) else {}
    target = str(entry.get("matching_target") or "ANY")
    if target not in ("ANY", "IP"):
        unsupported.append(f"{label}: Ziel-Typ {_text(target, 20)}")
    ips: list[str] = []
    raw_ips = entry.get("ips")
    if isinstance(raw_ips, list):
        for raw in raw_ips[:_MAX_IPS]:
            if cleaned := _ip_entry(raw):
                ips.append(cleaned)
            else:
                unsupported.append(f"{label}: IP-Format")
        if len(raw_ips) > _MAX_IPS:
            unsupported.append(f"{label}: zu viele IPs")
    port_type = str(entry.get("port_matching_type") or "ANY")
    port = ""
    if port_type == "SPECIFIC":
        raw_port = str(entry.get("port") or "").replace(" ", "")
        if _PORTS.match(raw_port):
            port = raw_port
        else:
            unsupported.append(f"{label}: Port-Format")
    elif port_type not in ("ANY", "OBJECT"):
        unsupported.append(f"{label}: Port-Typ {_text(port_type, 20)}")
    if entry.get("match_opposite_ips") or entry.get("match_opposite_ports"):
        unsupported.append(f"{label}: negierte Zuordnung")
    return {"zoneId": _id(entry.get("zone_id")), "target": target if target in ("ANY", "IP") else "OTHER",
            "ips": ips, "ipGroupId": _id(entry.get("ip_group_id")), "portType": port_type if port_type in (
                "ANY", "SPECIFIC", "OBJECT") else "OTHER", "port": port, "portGroupId": _id(entry.get("port_group_id"))}


def _policy(entry: dict, site: str) -> dict | None:
    policy_id = _id(entry.get("_id"))
    index = entry.get("index")
    if not policy_id or not isinstance(index, int) or isinstance(index, bool):
        return None
    unsupported: list[str] = []
    action = str(entry.get("action") or "")
    if action not in _ACTIONS:
        unsupported.append("Aktion")
    protocol = str(entry.get("protocol") or "all").lower()
    if protocol not in _PROTOCOLS:
        unsupported.append("Protokoll")
    ip_version = str(entry.get("ip_version") or "BOTH")
    if ip_version not in _IP_VERSIONS:
        unsupported.append("IP-Version")
    state = str(entry.get("connection_state_type") or "ALL")
    if state not in _STATES:
        unsupported.append("Verbindungsstatus")
    elif state == "CUSTOM":
        unsupported.append("Verbindungsstatus benutzerdefiniert")
    schedule = entry.get("schedule")
    mode = str((schedule or {}).get("mode") or "ALWAYS") if isinstance(schedule, dict) else "ALWAYS"
    if mode != "ALWAYS":
        unsupported.append("Zeitplan")
    if entry.get("match_ip_sec"):
        unsupported.append("IPsec-Zuordnung")
    if entry.get("match_opposite_protocol"):
        unsupported.append("negiertes Protokoll")
    source = _side(entry.get("source"), unsupported, "Quelle")
    destination = _side(entry.get("destination"), unsupported, "Ziel")
    return {"kind": "policy", "key": f"policy:{site}:{policy_id}", "data": {
        "site": site, "id": policy_id, "name": _text(entry.get("name")), "index": index,
        "enabled": bool(entry.get("enabled", True)), "predefined": bool(entry.get("predefined")),
        "action": action if action in _ACTIONS else "OTHER", "protocol": protocol if protocol in _PROTOCOLS else "other",
        "ipVersion": ip_version if ip_version in _IP_VERSIONS else "OTHER",
        "connectionState": state if state in _STATES else "OTHER",
        "source": source, "destination": destination, "unsupported": sorted(set(unsupported))}}


def _group(entry: dict, site: str) -> dict | None:
    group_id, group_type = _id(entry.get("_id")), str(entry.get("group_type") or "")
    if not group_id or group_type not in _GROUP_TYPES:
        return None
    members: list[str] = []
    unsupported = False
    raw = entry.get("group_members")
    for item in (raw[:_MAX_MEMBERS] if isinstance(raw, list) else []):
        if group_type == "port-group":
            text = str(item or "").strip()
            cleaned = text if text.isdigit() and 0 < int(text) < 65536 else ""
        else:
            cleaned = _ip_entry(item)
        if cleaned:
            members.append(cleaned)
        else:
            unsupported = True  # CIDR, IPv6 ranges, port ranges ... : the evaluation must say "unclear"
    if isinstance(raw, list) and len(raw) > _MAX_MEMBERS:
        unsupported = True
    return {"kind": "group", "key": f"group:{site}:{group_id}", "data": {
        "site": site, "id": group_id, "name": _text(entry.get("name")), "groupType": group_type,
        "members": members, "unsupported": unsupported}}


async def probe(base_url: str, api_key: str, account_id: str,
                controller_system_id: str | None) -> dict:
    """`{ok, error, facts: [{kind, key, data}]}`; read-only, API key only, all or nothing."""
    fail = {"ok": False, "facts": []}
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {**fail, "error": "Keine Adresse für die UniFi-API hinterlegt."}
    if not api_key:
        return {**fail, "error": "Der UniFi API-Key fehlt."}
    if not _KEY.match(api_key):
        return {**fail, "error": "Ungültiger UniFi API-Key (Leerzeichen oder Zeilenumbruch?)."}
    facts: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, follow_redirects=False,
                                     headers={"X-API-Key": api_key}) as client:
            root = f"{base}/proxy/network"
            sites = [s for s in await _get_json(client, f"{root}/api/self/sites")
                     if _SITE_NAME.match(str(s.get("name") or ""))]
            policies = zones = groups = 0
            for site in sites:
                name = site["name"]
                for entry in await _get_json(client, f"{root}/v2/api/site/{name}/firewall/zone"):
                    if (fact := _zone(entry, name)) is not None:
                        facts.append(fact)
                        zones += 1
                for entry in await _get_json(client, f"{root}/v2/api/site/{name}/firewall-policies"):
                    if (fact := _policy(entry, name)) is not None:
                        facts.append(fact)
                        policies += 1
                for entry in await _get_json(client, f"{root}/api/s/{name}/rest/firewallgroup"):
                    if (fact := _group(entry, name)) is not None:
                        facts.append(fact)
                        groups += 1
                if policies > _MAX_POLICIES or zones > _MAX_ZONES or groups > _MAX_GROUPS:
                    return {**fail, "error": "Zu viele Firewall-Regeln für eine vollständige Auswertung."}
    except _Unreadable as exc:
        return {**fail, "error": str(exc)}
    except httpx.HTTPError as exc:
        return {**fail, "error": f"UniFi-Firewall nicht lesbar: {type(exc).__name__}"}
    return {"ok": True, "error": "", "facts": facts}
