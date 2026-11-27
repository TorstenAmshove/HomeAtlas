"""Reads port forwards, the WAN address and client attachment from the classic UniFi Network API (ADR-0016).

The official integration API (`unifi_probe.py`) lists WANs with id and name only and has no port
forwards, so this module reads them from the classic API under ``/proxy/network/api``. The same
integration API key (header ``X-API-Key``) is accepted there (spike on UniFi Network 11.0.103), so
there is no login, no cookie, no CSRF token and no local user: every request is a GET against one of
seven fixed paths (sites, ``rest/portforward``, ``stat/device``, ``rest/networkconf``, ``stat/sta``,
``rest/portconf``; ADR-0025, ADR-0026),
redirects are not followed. Note the trade-off recorded in ADR-0016: the key has the rights of whoever
created it.

Opt-in like every source: only accounts of category ``unifi`` with ``allowProbe`` are used
(pipeline.py, the same accounts as `unifi_probe.py`), and only while ``scanEnableUnifiClassic`` is
on. The key never leaves this module (not in errors, not in results), and error texts never contain a
response body. This module must not import `unifi_live.py` (ADR-0015 keeps the scan separate); the
small GET helper is duplicated on purpose.

WAN status (ADR-0018): `wans` has one entry per WAN connection, matched by name to the rows
`unifi_probe.py` created. Only the active connection gets an address. A public interface address is
authoritative; behind an upstream router the interface is private and only the gateway's `geo_info` is
left, which can lag behind a reconnect (`origin: geo`, see exposure.py). From `networkconf` only name,
purpose, group and type are kept, never the credentials of a PPPoE connection.

Client attachment (ADR-0025): `stat/sta` yields per client only the MAC, wired or not, the switch MAC
and port or the AP MAC and SSID. Name, IP, hostname and every ``x_*`` field are never copied. Failing
to read it only costs a warning; forwards and WAN status stay.

Port VLANs (ADR-0025, ADR-0026, ADR-0027): per switch (`type == "usw"`) or gateway (`_GATEWAY_TYPES`, WAN port
left out) and port only number, name, profile name,
native network and tagged mode are kept. Network IDs come from `networkconf` (`_id`, `vlan`) and are
resolved *here* to VLAN ID and name per site; no ID is ever returned. Precedence per field: port override,
then the port profile, then the direct field of the port. The tagged list of mode `custom` is not read.
The site's default network (no `vlan` key) is flagged `default: true` where it appears, and every port
carries `defaultVlan` (its VLAN ID or `None`): UniFi never tags the default network, so mode `all` does
not include it (#260).

Device uplinks (ADR-0027): from the `uplink` object of each device only `type`, `uplink_device_name`,
`uplink_remote_port` and `port_idx` are read. A wired uplink whose `uplink_device_name` matches exactly one
device *of the same site* becomes `{site, mac, deviceMac, remotePort}` (the port is the one on the
neighbour); the name itself is never returned. Wireless, malformed, unresolvable or ambiguous uplinks yield
nothing. The switch port that is the device's own uplink is flagged `uplink: True`. Counters, IPs, MACs and
WAN data inside `uplink` are dropped.
"""
from __future__ import annotations

import ipaddress
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SITE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_FORWARDS = 500
_PORT = re.compile(r"^\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*$")


_MAX_CLIENTS = 2000
_MAX_PORTS = 128
_MAX_UPLINKS = 500
_MAX_PROFILES = 200
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(value: object) -> str:
    """Lower-case, colon separated; empty when the value is no MAC."""
    text = re.sub(r"[-.:\s]", "", str(value or "")).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", text):
        return ""
    mac = ":".join(text[i:i + 2] for i in range(0, 12, 2))
    return mac if _MAC.match(mac) else ""


_KEY = re.compile(r"^[\x21-\x7e]{8,512}$")
_GATEWAY_TYPES = ("udm", "ugw", "uxg")


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


def _public(value: object) -> str:
    ip = _ip(value)
    return ip if ip and ipaddress.ip_address(ip).is_global else ""


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _wan_status(networks: list[dict], devices: list[dict]) -> list[dict]:
    """One entry per WAN connection; only the active one carries an address."""
    gateway = next((d for d in devices if d.get("type") in _GATEWAY_TYPES), {})
    interfaces, status = _mapping(gateway.get("last_wan_interfaces")), _mapping(gateway.get("last_wan_status"))
    geo = _mapping(gateway.get("geo_info"))
    uplink_group = str(_mapping(gateway.get("uplink")).get("comment") or "")
    wans = []
    for network in networks:
        if network.get("purpose") != "wan":
            continue
        group = str(network.get("wan_networkgroup") or "")
        interface = _mapping(interfaces.get(group))
        online = status.get(group) == "online" and interface.get("alive") is not False
        active = online and (group == uplink_group if uplink_group in interfaces else True)
        interface_ip = _ip(interface.get("ip")) if active else ""
        interface_public = _public(interface_ip)
        public_ip = interface_public or (_public(_mapping(geo.get(group)).get("address")) if active else "")
        wans.append({"name": str(network.get("name") or "")[:100], "group": group[:20],
                     "type": str(network.get("wan_type") or "")[:20], "active": active,
                     "ip": public_ip or interface_ip, "interfaceIp": interface_ip, "publicIp": public_ip,
                     "publicOrigin": ("interface" if interface_public else "geo") if public_ip else ""})
    return wans


def _forward(entry: dict) -> dict | None:
    """Only proto, ports, destination and the enabled flag; name, source filter etc. are dropped."""
    dest, wan_port, dest_port = _ip(entry.get("fwd")), _port(entry.get("dst_port")), _port(entry.get("fwd_port"))
    if not dest or not wan_port or not dest_port:
        return None
    proto = str(entry.get("proto") or "tcp_udp").lower()
    proto = {"tcp_udp": "TCP/UDP", "tcp": "TCP", "udp": "UDP"}.get(proto, "TCP/UDP")
    return {"proto": proto, "wanPort": wan_port, "destIp": dest, "destPort": dest_port,
            "enabled": bool(entry.get("enabled", True))}


def _client(entry: dict, site: str) -> dict | None:
    """Only the allowlisted attachment fields (ADR-0025); None without a usable MAC."""
    mac = normalize_mac(entry.get("mac"))
    if not mac:
        return None
    ap_mac = normalize_mac(entry.get("ap_mac"))
    wired = entry.get("is_wired")
    if not isinstance(wired, bool):
        wired = False if ap_mac else None
    if wired is None:
        return None
    port = entry.get("sw_port")
    port = port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 999 else None
    essid = entry.get("essid")
    essid = essid.strip()[:64] if isinstance(essid, str) and essid.strip() else ""
    return {"site": site, "mac": mac, "wired": wired,
            "swMac": normalize_mac(entry.get("sw_mac")) if wired else "", "swPort": port if wired else None,
            "apMac": ap_mac if not wired else "", "essid": essid if not wired else ""}


def _vlan_id(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 4094 else None


def _networks(raw: list[dict]) -> dict[str, dict]:
    """`_id` -> `{vlan, name[, default]}`; the default network has no `vlan` and counts as VLAN 1.

    The default network (first `corporate` entry without a `vlan` key) is flagged `default: True`:
    UniFi carries it untagged only, "allow all" on a port means the VLAN networks (#260). A network
    explicitly configured with VLAN ID 1 is not flagged."""
    result: dict[str, dict] = {}
    has_default = False
    for entry in raw:
        net_id = entry.get("_id")
        if not isinstance(net_id, str) or not net_id or entry.get("purpose") == "wan":
            continue
        vlan = _vlan_id(entry.get("vlan"))
        is_default = False
        if vlan is None and "vlan" not in entry and entry.get("purpose") == "corporate":
            vlan = 1
            is_default = not has_default
            has_default = True
        result[net_id] = {"vlan": vlan, "name": str(entry.get("name") or "")[:100]}
        if is_default:
            result[net_id]["default"] = True
    return result


def _default_vlan(networks: dict[str, dict]) -> int | None:
    """VLAN ID of the site's default network, `None` when the site has none."""
    return next((n["vlan"] for n in networks.values() if n.get("default")), None)


def _profiles(raw: list[dict]) -> tuple[dict[str, dict], bool]:
    """`_id` -> allowlisted profile fields; second value tells whether the cap cut the list."""
    result: dict[str, dict] = {}
    for entry in raw:
        profile_id = entry.get("_id")
        if not isinstance(profile_id, str) or not profile_id:
            continue
        if len(result) >= _MAX_PROFILES:
            return result, True
        result[profile_id] = {k: entry.get(k) for k in _PORT_FIELDS}
        result[profile_id]["name"] = entry.get("name")
    return result, False


_PORT_FIELDS = ("native_networkconf_id", "tagged_vlan_mgmt", "excluded_networkconf_ids")


def _port_index(entry: dict) -> int | None:
    idx = entry.get("port_idx")
    return idx if isinstance(idx, int) and not isinstance(idx, bool) and 1 <= idx <= 999 else None


def _resolve_network(net_id: object, networks: dict[str, dict]) -> dict:
    if not net_id:  # nothing configured: not an unknown network
        return {"vlan": None, "name": "", "known": True}
    found = networks.get(net_id) if isinstance(net_id, str) else None
    if found is None:
        return {"vlan": None, "name": "", "known": False}
    resolved = {"vlan": found["vlan"], "name": found["name"], "known": True}
    if found.get("default"):
        resolved["default"] = True
    return resolved


def _own_uplink_port(device: dict) -> int | None:
    """`uplink.port_idx` of a wired uplink, the port of this device that leads to its neighbour."""
    uplink = _mapping(device.get("uplink"))
    return _port_index({"port_idx": uplink.get("port_idx")}) if uplink.get("type") == "wire" else None


def _remote_port(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 999 else None


def _uplinks(site: str, devices: list[dict]) -> list[dict]:
    """Wired device-to-device uplinks of one site (ADR-0027); the neighbour is resolved by exact, unique name."""
    names: dict[str, list[str]] = {}
    for device in devices:
        name, mac = device.get("name"), normalize_mac(device.get("mac"))
        if isinstance(name, str) and name and mac:
            names.setdefault(name, []).append(mac)
    result = []
    for device in devices:
        mac, uplink = normalize_mac(device.get("mac")), _mapping(device.get("uplink"))
        target, port = uplink.get("uplink_device_name"), _remote_port(uplink.get("uplink_remote_port"))
        if not mac or uplink.get("type") != "wire" or port is None or not isinstance(target, str):
            continue
        found = names.get(target, [])
        if len(found) == 1 and found[0] != mac:
            result.append({"site": site, "mac": mac, "deviceMac": found[0], "remotePort": port})
    return result


def _switch_ports(device: dict, profiles: dict[str, dict], networks: dict[str, dict]) -> list[dict]:
    """Effective VLAN setup per port: override > profile > direct port field (ADR-0026).

    Gateways leave out their WAN port (`is_uplink` or the own uplink port); a switch flags the port that
    leads to its uplink neighbour with `uplink: True` (ADR-0027)."""
    gateway = device.get("type") in _GATEWAY_TYPES
    own_uplink = _own_uplink_port(device)
    uplink_named = isinstance(_mapping(device.get("uplink")).get("uplink_device_name"), str) and bool(
        _mapping(device.get("uplink")).get("uplink_device_name"))
    overrides = {i: e for e in device.get("port_overrides") or [] if isinstance(e, dict)
                 and (i := _port_index(e)) is not None}
    ports = []
    seen: set[int] = set()
    default_vlan = _default_vlan(networks)
    for entry in device.get("port_table") or []:
        idx = _port_index(entry) if isinstance(entry, dict) else None
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        if gateway and (entry.get("is_uplink") is True or idx == own_uplink):
            continue
        if len(ports) >= _MAX_PORTS:
            break
        override = overrides.get(idx, {})
        profile_id = override.get("portconf_id") or entry.get("portconf_id")
        profile = profiles.get(profile_id) if isinstance(profile_id, str) else None

        def field(key: str):
            for source in (override, profile or {}, entry):
                if source.get(key) is not None:
                    return source[key]
            return None

        mgmt = field("tagged_vlan_mgmt")
        mode = "" if not isinstance(mgmt, str) or not mgmt else {"auto": "all", "block_all": "none"}.get(mgmt, "custom")
        excluded = field("excluded_networkconf_ids")
        excluded = excluded if isinstance(excluded, list) else []
        name = override.get("name") or entry.get("name")
        ports.append({
            "port": idx, "name": str(name or "")[:64],
            "profile": str((profile or {}).get("name") or "")[:100],
            "native": _resolve_network(field("native_networkconf_id"), networks),
            "defaultVlan": default_vlan,
            "tagged": {"mode": mode, "vlans": [],
                       "excluded": [{k: v for k, v in _resolve_network(i, networks).items() if k != "known"}
                                    for i in excluded[:_MAX_PORTS] if mode == "all"]}})
        if not gateway and uplink_named and idx == own_uplink:
            ports[-1]["uplink"] = True
    return sorted(ports, key=lambda p: p["port"])


def _switches(site: str, devices: list[dict], profiles: dict[str, dict], networks: dict[str, dict]) -> list[dict]:
    result = []
    for device in devices:
        mac = normalize_mac(device.get("mac"))
        if device.get("type") in ("usw", *_GATEWAY_TYPES) and mac:
            result.append({"site": site, "mac": mac, "ports": _switch_ports(device, profiles, networks)})
    return result


async def probe(base_url: str, api_key: str, account_id: str,
                controller_system_id: str | None) -> dict:
    """`{ok, error, forwards, wans, wanFacts, clients, switches, uplinks, portsOk, warnings}`; read-only, API key only."""
    fail = {"ok": False, "forwards": [], "wans": [], "wanFacts": [], "clients": [],
            "switches": [], "uplinks": [], "portsOk": False, "warnings": []}
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {**fail, "error": "Keine Adresse für die klassische UniFi-API hinterlegt."}
    if not api_key:
        return {**fail, "error": "Der UniFi API-Key fehlt."}
    if not _KEY.match(api_key):
        return {**fail, "error": "Ungültiger UniFi API-Key (Leerzeichen oder Zeilenumbruch?)."}
    forwards: list[dict] = []
    wans: list[dict] = []
    wan_facts: list[dict] = []
    clients: list[dict] = []
    warnings: list[str] = []
    switches: list[dict] = []
    uplinks: list[dict] = []
    capped_uplinks = False
    ports_ok = True
    capped = False
    capped_profiles = False
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
                try:  # client attachment is optional: forwards and WAN status stay when it fails
                    for entry in await _get_data(client, api, f"/s/{name}/stat/sta"):
                        if (found := _client(entry, name)) is None:
                            continue
                        if len(clients) < _MAX_CLIENTS:
                            clients.append(found)
                        else:
                            capped = True
                except (PermissionError, ValueError, httpx.HTTPError) as exc:
                    warnings.append(f"Client-Zuordnung nicht lesbar ({type(exc).__name__}).")
                errors: dict[str, Exception] = {}
                raw: dict[str, list[dict]] = {}
                for key, path in (("networks", "rest/networkconf"), ("devices", "stat/device"),
                                  ("profiles", "rest/portconf")):
                    try:  # each source is optional: forwards stay when one cannot be read
                        raw[key] = await _get_data(client, api, f"/s/{name}/{path}")
                    except (PermissionError, ValueError, httpx.HTTPError) as exc:
                        errors[key] = exc
                if "networks" in errors or "devices" in errors:
                    exc = errors.get("networks") or errors["devices"]
                    warnings.append(f"WAN-Status nicht lesbar ({type(exc).__name__}).")
                else:
                    site_wans = _wan_status(raw["networks"], raw["devices"])
                    wans += site_wans
                    wan_facts += [{"kind": "wan_address", "key": f"unifi:{name}:{w['group']}",
                                   "data": {"ip": w["publicIp"], "source": "UniFi", "origin": w["publicOrigin"]}}
                                  for w in site_wans if w["publicIp"]]
                if errors:
                    ports_ok = False
                    exc = next(iter(errors.values()))
                    warnings.append(f"Port-VLANs nicht lesbar ({type(exc).__name__}).")
                else:
                    profiles, profiles_capped = _profiles(raw["profiles"])
                    capped_profiles = capped_profiles or profiles_capped
                    switches += _switches(name, raw["devices"], profiles, _networks(raw["networks"]))
                    for found in _uplinks(name, raw["devices"]):
                        if len(uplinks) < _MAX_UPLINKS:
                            uplinks.append(found)
                        else:
                            capped_uplinks = True
    except PermissionError as exc:
        return {**fail, "error": str(exc)}
    except ValueError as exc:  # fixed German texts from _get_data only
        return {**fail, "error": str(exc)}
    except httpx.HTTPError as exc:
        return {**fail, "error": f"Klassische UniFi-API nicht lesbar: {type(exc).__name__}"}
    if capped:
        warnings.append(f"Mehr als {_MAX_CLIENTS} Clients, der Rest wird nicht zugeordnet.")
    if capped_profiles:
        warnings.append(f"Mehr als {_MAX_PROFILES} Port-Profile, der Rest wird nicht aufgelöst.")
    if capped_uplinks:
        warnings.append(f"Mehr als {_MAX_UPLINKS} Geräte-Uplinks, der Rest wird nicht zugeordnet.")
    if any(len(sw["ports"]) >= _MAX_PORTS for sw in switches):
        warnings.append(f"Mehr als {_MAX_PORTS} Ports an einem Switch, der Rest wird nicht gelesen.")
    forwards.append({"kind": "portforward_scan", "key": "scan", "data": {"count": len(forwards)}})
    return {"ok": True, "error": "", "forwards": forwards, "wans": wans, "wanFacts": wan_facts,
            "clients": clients, "switches": switches, "uplinks": uplinks, "portsOk": ports_ok, "warnings": warnings}
