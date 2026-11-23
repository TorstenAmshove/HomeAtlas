"""Write-capable switching of Home Assistant `switch`/`light` entities and shutter-class `cover`s --
the counterpart `probe_auth.probe_homeassistant` explicitly is not.

This is the only write-capable device module HomeAtlas has left (ADR-0023): there is no remote
administration, and Shelly relays are no longer switched directly -- switching goes through Home
Assistant. This file only ever sends a state-changing request, never imports a read-only module,
and duplicates the small amount of connection setup it needs (HA's Bearer header) rather than
sharing it. Any further member action would be added here, only reachable via `tools.py`, each with
its own ADR and a fixed allowlist.

Unlike every other write module in this codebase, this one *is* reachable from `tools.py` --
that's a deliberate, explicit product decision (switching a light or plug is judged safe enough
for the assistant to do directly, unlike editing inventory/docs) and
is documented at the point of exposure in `tools.py`, not a loophole.

Scope is deliberately narrow: on/off only for the `switch` and `light` domains
(`_HA_ALLOWED_DOMAINS`), plus open/close/stop (never a position) for shutter-like `cover` entities
(`ha_set_cover`, ADR-0013). A cover qualifies only if its `device_class` is on the allowlist
`_COVER_ALLOWED_CLASSES`; garage doors, gates, doors, windows and covers without a device_class stay
blocked (a prompt-injected "open the garage" would be a burglary risk). Never `lock`, `climate`,
`alarm_control_panel` or anything else HA might expose, even though the REST call shape would
happily accept them.
"""
from __future__ import annotations

import re

import httpx

_TIMEOUT = httpx.Timeout(8.0, connect=3.0)

_HA_ALLOWED_DOMAINS = ("switch", "light")

# device_class values of `cover` entities that may be moved. Allowlist, not blocklist: anything
# else, including a missing device_class, is refused. Duplicated in `probe_auth` (read side, must
# not import this module); a test keeps both in sync.
_COVER_ALLOWED_CLASSES = ("blind", "shade", "shutter", "curtain", "awning")  # never `window` (ADR-0018)
_COVER_ACTIONS = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}
_COVER_ENTITY_RE = re.compile(r"^cover\.[a-z0-9_]+$")


async def ha_set_switch(base_url: str, token: str, entity_id: str, on: bool) -> dict:
    """Flips one Home Assistant entity via `POST /api/services/{domain}/turn_on|turn_off`.
    `entity_id`'s domain (the part before the dot, e.g. "switch" in "switch.wohnzimmer_stecker")
    picks the service to call, and is checked against `_HA_ALLOWED_DOMAINS` before any request is
    made -- see module docstring for why the scope stops at switches and lights."""
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        return {"ok": False, "error": "Keine Adresse für Home Assistant hinterlegt."}
    if not token:
        return {"ok": False, "error": "Kein Zugriffstoken hinterlegt."}
    domain = (entity_id or "").split(".", 1)[0]
    if domain not in _HA_ALLOWED_DOMAINS:
        return {"ok": False, "error": (
            f"„{entity_id}“ gehört zur Domäne „{domain}“ -- geschaltet werden dürfen hier nur "
            f"switch/light-Entities ({', '.join(_HA_ALLOWED_DOMAINS)}).")}
    service = "turn_on" if on else "turn_off"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, headers=headers) as client:
            response = await client.post(
                f"{base_url}/api/services/{domain}/{service}", json={"entity_id": entity_id})
        if response.status_code in (401, 403):
            return {"ok": False, "error": f"Home Assistant hat das Zugriffstoken abgelehnt (HTTP {response.status_code})."}
        if response.status_code >= 400:
            return {"ok": False, "error": f"Home Assistant hat mit HTTP {response.status_code} abgelehnt."}
        return {"ok": True, "error": ""}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Home Assistant unter {base_url} nicht erreichbar: {exc}"}


async def ha_set_cover(base_url: str, token: str, entity_id: str, action: str) -> dict:
    """Opens, closes or stops one shutter-like Home Assistant cover. The entity's `device_class` is
    read live (`GET /api/states/{id}`) immediately before the POST and must be in
    `_COVER_ALLOWED_CLASSES`; the gap between check and POST is accepted (ADR-0013). No position
    setting exists here on purpose."""
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        return {"ok": False, "error": "Keine Adresse für Home Assistant hinterlegt."}
    if not token:
        return {"ok": False, "error": "Kein Zugriffstoken hinterlegt."}
    if action not in _COVER_ACTIONS:
        return {"ok": False, "error": "Unbekannte Aktion -- erlaubt sind nur open, close und stop."}
    if not _COVER_ENTITY_RE.match(entity_id or ""):
        return {"ok": False, "error": (
            f"„{entity_id}“ ist keine cover-Entity -- hier dürfen nur Rollos bewegt werden.")}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, headers=headers) as client:
            state = await client.get(f"{base_url}/api/states/{entity_id}")
            if state.status_code in (401, 403):
                return {"ok": False, "error": f"Home Assistant hat das Zugriffstoken abgelehnt (HTTP {state.status_code})."}
            if state.status_code == 404:
                return {"ok": False, "error": f"„{entity_id}“ ist in Home Assistant nicht bekannt."}
            if state.status_code >= 400:
                return {"ok": False, "error": f"Home Assistant hat mit HTTP {state.status_code} abgelehnt."}
            try:
                attrs = (state.json() or {}).get("attributes") or {}
            except ValueError:
                return {"ok": False, "error": "Home Assistant lieferte keine lesbare Antwort."}
            device_class = str(attrs.get("device_class") or "").strip().lower()
            if device_class not in _COVER_ALLOWED_CLASSES:
                return {"ok": False, "error": (
                    f"„{entity_id}“ ist kein Rollo (device_class „{device_class or 'fehlt'}“) -- Tore, Türen "
                    "und Garagentore dürfen nicht bewegt werden.")}
            response = await client.post(
                f"{base_url}/api/services/cover/{_COVER_ACTIONS[action]}", json={"entity_id": entity_id})
        if response.status_code in (401, 403):
            return {"ok": False, "error": f"Home Assistant hat das Zugriffstoken abgelehnt (HTTP {response.status_code})."}
        if response.status_code >= 400:
            return {"ok": False, "error": f"Home Assistant hat mit HTTP {response.status_code} abgelehnt."}
        return {"ok": True, "error": ""}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Home Assistant unter {base_url} nicht erreichbar: {exc}"}
