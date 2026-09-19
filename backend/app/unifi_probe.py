"""Read the official local UniFi Network API without exposing controller write capabilities.

The UCG's documented local API lives below ``/proxy/network/integration/v1`` and authenticates
with a dedicated API key. Every request in this module is a fixed GET endpoint; no generic request
helper or user-supplied path exists, so the scan pipeline cannot become a controller admin API.
"""
from __future__ import annotations

import asyncio
import ipaddress

import httpx

from . import oui

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_PAGE_SIZE = 200
_DETAIL_CONCURRENCY = 8


class _ApiError(Exception):
    pass


async def _get(client: httpx.AsyncClient, base_url: str, path: str, **params) -> dict:
    response = await client.get(f"{base_url}{path}", params=params or None)
    if response.status_code in (401, 403):
        raise PermissionError("Der UniFi API-Key wurde abgelehnt.")
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise _ApiError("Unerwartete Antwort (kein JSON-Objekt).")
    return result


async def _all_pages(client: httpx.AsyncClient, base_url: str, path: str) -> list[dict]:
    offset, entries = 0, []
    while True:
        page = await _get(client, base_url, path, offset=offset, limit=_PAGE_SIZE)
        data = page.get("data")
        if not isinstance(data, list):
            raise _ApiError("Unerwartete Antwort (keine Ergebnisliste).")
        entries += [entry for entry in data if isinstance(entry, dict)]
        total = page.get("totalCount")
        if not isinstance(total, int) or offset + len(data) >= total or not data:
            return entries
        offset += len(data)


def _api_base(base_url: str) -> str:
    return f"{(base_url or '').rstrip('/')}/proxy/network/integration/v1"


def _kind(features: object) -> str:
    return "router" if isinstance(features, list) and "gateway" in features else "network"


def _purpose(features: object) -> str:
    if isinstance(features, list) and "gateway" in features:
        return "Internet-Router/Gateway (UniFi)"
    if isinstance(features, list) and "accessPoint" in features:
        return "WLAN-Access-Point (UniFi)"
    if isinstance(features, list) and "switching" in features:
        return "Netzwerk-Switch (UniFi)"
    return "Netzwerk-Gerät (UniFi)"


def _status(value: str) -> str:
    return "online" if value == "ONLINE" else "offline" if value else "unknown"


def _device_system(site: dict, device: dict, detail: dict) -> dict | None:
    mac = oui.normalize_mac(device.get("macAddress") or detail.get("macAddress") or "")
    device_id = device.get("id") or detail.get("id") or ""
    if not mac or not device_id:
        return None
    features = device.get("features") or []
    uplink = detail.get("uplink") or {}
    return {
        "discoveryKey": f"mac:{mac}",
        "kind": _kind(features),
        "name": device.get("name") or device.get("model") or "UniFi-Gerät",
        "ip": device.get("ipAddress") or "",
        "mac": mac,
        "location": site.get("name") or "",
        "vendor": "Ubiquiti",
        "model": device.get("model") or "",
        "purpose": _purpose(features),
        "status": _status(device.get("state") or ""),
        "discovered": 1,
        "discoverySource": "unifi",
        "extra": {"unifi": {
            "siteId": site.get("id") or "", "siteName": site.get("name") or "", "deviceId": device_id,
            "firmwareVersion": device.get("firmwareVersion") or "", "features": features,
            "interfaces": device.get("interfaces") or [], "uplinkDeviceId": uplink.get("deviceId") or "",
        }},
    }


def _client_system(site: dict, client: dict) -> dict | None:
    if client.get("type") not in ("WIRED", "WIRELESS"):
        return None
    mac = oui.normalize_mac(client.get("macAddress") or "")
    if not mac:
        return None
    return {
        "discoveryKey": f"mac:{mac}",
        "name": client.get("name") or "UniFi-Client",
        "ip": client.get("ipAddress") or "",
        "mac": mac,
        "location": site.get("name") or "",
        "vendor": oui.lookup(mac),
        "status": "online",
        "discovered": 1,
        "discoverySource": "unifi",
        "extra": {"unifi": {
            "siteId": site.get("id") or "", "siteName": site.get("name") or "", "clientId": client.get("id") or "",
            "clientType": client.get("type") or "", "uplinkDeviceId": client.get("uplinkDeviceId") or "",
            "access": ((client.get("access") or {}).get("type") or ""),
        }},
    }


def _network_resource(site: dict, network: dict, owner_system_id: str | None) -> dict:
    ipv4 = network.get("ipv4Configuration") or {}
    host, prefix = ipv4.get("hostIpAddress") or "", ipv4.get("prefixLength")
    try:
        cidr = str(ipaddress.ip_interface(f"{host}/{prefix}").network)
    except ValueError:
        cidr = ""
    dhcp_range = ((ipv4.get("dhcpConfiguration") or {}).get("ipAddressRange") or {})
    start, stop = dhcp_range.get("start") or "", dhcp_range.get("stop") or ""
    return {
        "kind": "network", "source": "unifi", "siteExternalId": site.get("id") or "",
        "siteName": site.get("name") or "", "externalId": network.get("id") or "", "name": network.get("name") or "Netzwerk",
        "enabled": bool(network.get("enabled")), "ownerSystemId": owner_system_id,
        "facts": {
            "vlanId": network.get("vlanId"), "cidr": cidr, "gateway": host,
            "dhcpRange": f"{start} - {stop}" if start and stop else "", "management": network.get("management") or "",
            "isolationEnabled": bool(network.get("isolationEnabled")),
        },
    }


def _wifi_resource(site: dict, wifi: dict, owner_system_id: str | None) -> dict:
    network = wifi.get("network") or {}
    security = wifi.get("securityConfiguration") or {}
    return {
        "kind": "wifi", "source": "unifi", "siteExternalId": site.get("id") or "",
        "siteName": site.get("name") or "", "externalId": wifi.get("id") or "", "name": wifi.get("name") or "WLAN",
        "enabled": bool(wifi.get("enabled")), "ownerSystemId": owner_system_id,
        "facts": {"networkExternalId": network.get("networkId") or "", "security": security.get("type") or "",
                  "type": wifi.get("type") or ""},
    }


def _wan_resource(site: dict, wan: dict, owner_system_id: str | None) -> dict:
    return {
        "kind": "wan", "source": "unifi", "siteExternalId": site.get("id") or "",
        "siteName": site.get("name") or "", "externalId": wan.get("id") or "", "name": wan.get("name") or "Internet",
        "enabled": True, "ownerSystemId": owner_system_id, "facts": {},
    }


async def probe(base_url: str, api_key: str, account_id: str, controller_system_id: str | None) -> dict:
    """Return discovered systems and documentation resources from every local UniFi site."""
    if not base_url:
        return {"ok": False, "error": "Keine Adresse fuer den UniFi Controller hinterlegt.", "warnings": [],
                "systems": [], "resources": [], "completeScopes": []}
    if not api_key:
        return {"ok": False, "error": "Der UniFi API-Key fehlt.", "warnings": [], "systems": [], "resources": [],
                "completeScopes": []}

    systems, resources, warnings, complete_scopes = [], [], [], []
    api_base = _api_base(base_url)
    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, headers=headers) as client:
            await _get(client, api_base, "/info")
            sites = await _all_pages(client, api_base, "/sites")
            for site in sites:
                site_id = site.get("id") or ""
                if not site_id:
                    continue
                try:
                    devices = await _all_pages(client, api_base, f"/sites/{site_id}/devices")
                except (httpx.HTTPError, _ApiError) as exc:
                    warnings.append(f"UniFi-Site {site.get('name') or site_id}: Geraete konnten nicht gelesen werden ({exc}).")
                    devices = []

                semaphore = asyncio.Semaphore(_DETAIL_CONCURRENCY)

                async def device_detail(device: dict) -> dict:
                    async with semaphore:
                        try:
                            return await _get(client, api_base, f"/sites/{site_id}/devices/{device.get('id')}")
                        except (httpx.HTTPError, _ApiError):
                            return {}

                details = await asyncio.gather(*(device_detail(device) for device in devices))
                for device, detail in zip(devices, details):
                    finding = _device_system(site, device, detail)
                    if finding is not None:
                        systems.append(finding)

                try:
                    clients = await _all_pages(client, api_base, f"/sites/{site_id}/clients")
                    systems += [finding for client_entry in clients if (finding := _client_system(site, client_entry)) is not None]
                except (httpx.HTTPError, _ApiError) as exc:
                    warnings.append(f"UniFi-Site {site.get('name') or site_id}: Clients konnten nicht gelesen werden ({exc}).")

                try:
                    networks = await _all_pages(client, api_base, f"/sites/{site_id}/networks")
                    network_details = await asyncio.gather(*(
                        _get(client, api_base, f"/sites/{site_id}/networks/{network.get('id')}") for network in networks
                    ))
                    resources += [_network_resource(site, network, controller_system_id) for network in network_details]
                    complete_scopes.append((site_id, "network"))
                except (httpx.HTTPError, _ApiError) as exc:
                    warnings.append(f"UniFi-Site {site.get('name') or site_id}: Netze konnten nicht gelesen werden ({exc}).")

                try:
                    wifi = await _all_pages(client, api_base, f"/sites/{site_id}/wifi/broadcasts")
                    resources += [_wifi_resource(site, entry, controller_system_id) for entry in wifi]
                    complete_scopes.append((site_id, "wifi"))
                except (httpx.HTTPError, _ApiError) as exc:
                    warnings.append(f"UniFi-Site {site.get('name') or site_id}: WLANs konnten nicht gelesen werden ({exc}).")

                try:
                    wans = await _all_pages(client, api_base, f"/sites/{site_id}/wans")
                    resources += [_wan_resource(site, entry, controller_system_id) for entry in wans]
                    complete_scopes.append((site_id, "wan"))
                except (httpx.HTTPError, _ApiError) as exc:
                    warnings.append(f"UniFi-Site {site.get('name') or site_id}: WANs konnten nicht gelesen werden ({exc}).")
    except PermissionError as exc:
        return {"ok": False, "error": str(exc), "warnings": [], "systems": [], "resources": [], "completeScopes": []}
    except (httpx.HTTPError, _ApiError, ValueError) as exc:
        return {"ok": False, "error": f"UniFi Controller nicht erreichbar: {exc}", "warnings": [], "systems": [],
                "resources": [], "completeScopes": []}
    return {"ok": True, "error": "", "warnings": warnings, "systems": systems, "resources": resources,
            "completeScopes": complete_scopes}
