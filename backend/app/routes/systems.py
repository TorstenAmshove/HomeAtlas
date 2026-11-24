"""Inventory: systems, duplicates/merge/aliases, config versions, device errors, and the
read-only credentialed probe of a single device (see probe_auth).

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

import asyncio

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

from .. import admin_links, classify, crypto, db, discovery, docs, exposure, llm_providers, pipeline, probe_auth
from .. import monitor as monitor_module
from ..deps import _public_account, current_user, require_admin

router = APIRouter()


class SystemWrite(BaseModel):
    """Hand-maintainable device fields only (POST/PATCH /api/systems).

    System fields (status, lastSeen, openPorts, discoveryKey, extra, ...) belong to scan/monitor and
    are silently ignored (`extra="ignore"`, so older clients that send the whole device keep
    working). The handlers pass only `exclude_unset` values on, so a save never writes back stale
    copies of fields the client did not change."""
    model_config = ConfigDict(extra="ignore")

    kind: str | None = None
    name: str | None = None
    hostname: str | None = None
    ip: str | None = None
    mac: str | None = None
    vendor: str | None = None
    model: str | None = None
    os: str | None = None
    location: str | None = None
    purpose: str | None = None
    descriptionMd: str | None = None
    url: str | None = None
    docUrl: str | None = None
    docLink: str | None = None
    notes: str | None = None
    importance: str | None = None
    parentId: str | None = None
    monitored: bool | StrictInt | None = None
    monitorPorts: list[int] | None = None
    tags: list[str] | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str | None) -> str:
        if v not in docs.KIND_LABELS:
            raise ValueError("Unbekannte Geräteart.")
        return v

    @field_validator("importance")
    @classmethod
    def _importance(cls, v: str | None) -> str:
        if v not in docs.IMPORTANCE_LABELS:
            raise ValueError("importance muss critical, normal oder low sein.")
        return v

    @field_validator("monitored")
    @classmethod
    def _monitored(cls, v: Any) -> bool:
        if v is None or (not isinstance(v, bool) and v not in (0, 1)):
            raise ValueError("monitored muss ein Wahrheitswert sein.")
        return bool(v)

    @field_validator("monitorPorts", mode="before")
    @classmethod
    def _ports(cls, v: Any) -> Any:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("monitorPorts muss eine Liste sein.")
        if len(v) > 3:
            raise ValueError("Höchstens 3 Ports.")
        for port in v:
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Ports müssen ganze Zahlen von 1 bis 65535 sein.")
        if len(set(v)) != len(v):
            raise ValueError("Ports dürfen nicht doppelt vorkommen.")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str]:
        return [t.strip() for t in (v or []) if t.strip()]

    def to_fields(self) -> dict:
        fields = self.model_dump(exclude_unset=True)
        if fields.get("monitorPorts") is None and "monitorPorts" in fields:
            fields["monitorPorts"] = []
        return fields


def _check_parent(system_id: str | None, parent_id: str | None) -> None:
    """parentId must exist, not be the device itself and not close a cycle."""
    if not parent_id:
        return
    if db.get_system(parent_id) is None:
        raise HTTPException(status_code=422, detail="Das übergeordnete Gerät existiert nicht.")
    seen: set[str] = set()
    current: str | None = parent_id
    while current and current not in seen:
        if system_id is not None and current == system_id:
            raise HTTPException(status_code=422, detail="Ein Gerät kann nicht (indirekt) sich selbst untergeordnet sein.")
        seen.add(current)
        node = db.get_system(current)
        current = node.get("parentId") if node else None


# ---------------------------------------------------------------------------------------------
# Systems
# ---------------------------------------------------------------------------------------------

@router.get("/api/systems")
async def list_systems(kind: str | None = None, _: dict = Depends(current_user)) -> dict:
    systems = db.list_systems(kind)
    accounts_by_system: dict[str, int] = {}
    for account in db.list_accounts():
        if account["systemId"]:
            accounts_by_system[account["systemId"]] = accounts_by_system.get(account["systemId"], 0) + 1
    error_counts = db.count_error_events_by_system()
    return {"systems": [{**s, "accountCount": accounts_by_system.get(s["id"], 0),
                         "errorCount": error_counts.get(s["id"], 0),
                         "description": docs.describe_device(s)} for s in systems],
            "kindLabels": docs.KIND_LABELS}


@router.get("/api/systems/duplicates")
async def duplicate_candidates(_: dict = Depends(require_admin)) -> dict:
    """Merge suggestions only; merging itself stays the explicit POST .../merge."""
    return {"candidates": db.find_duplicate_candidates()}


@router.get("/api/systems/{system_id}/aliases")
async def system_aliases(system_id: str, _: dict = Depends(require_admin)) -> dict:
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    return {"aliases": db.list_aliases(system_id)}


@router.post("/api/systems/{system_id}/not-duplicate")
async def not_duplicate(system_id: str, body: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    other_id = (body.get("otherId") or "").strip()
    if not other_id or other_id == system_id:
        raise HTTPException(status_code=400, detail="otherId fehlt oder entspricht dem Gerät selbst.")
    if db.get_system(system_id) is None or db.get_system(other_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    db.dismiss_duplicate(system_id, other_id)
    return {"ok": True}


@router.get("/api/systems/{system_id}")
async def get_system(system_id: str, _: dict = Depends(current_user)) -> dict:
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    accounts = [{**_public_account(a), "viaAssignment": False} for a in db.list_accounts(system_id)]
    accounts += [{**_public_account(a), "viaAssignment": True} for a in db.list_assigned_accounts(system_id)]
    return {"system": system, "accounts": accounts,
            # Derived rather than stored, so it stays correct as the device's data fills in.
            "description": docs.describe_device(system),
            "monitorPortsEffective": monitor_module.effective_ports(system)[0]}


@router.get("/api/systems/{system_id}/admin-links")
async def system_admin_links(system_id: str, _: dict = Depends(require_admin)) -> dict:
    """Deep links into Portainer / the Proxmox UI; an empty list (not 404) when none apply."""
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    parent = db.get_system(system["parentId"]) if system.get("parentId") else None
    urls = [a.get("url") or "" for a in db.list_accounts(system["parentId"])
            if a.get("category") == "proxmox"] if parent else []
    return {"links": admin_links.build(system, db.get_settings(), parent, urls)}


@router.post("/api/systems")
async def create_system(body: SystemWrite, _: dict = Depends(require_admin)) -> dict:
    fields = body.to_fields()
    _check_parent(None, fields.get("parentId"))
    # confirmed=1: anything a human typed is protected from being overwritten by the next scan.
    system = db.create_system({**fields, "confirmed": 1, "discovered": 0})
    return {"system": db.get_system(system["id"])}


@router.patch("/api/systems/{system_id}")
async def update_system(system_id: str, patch: SystemWrite, _: dict = Depends(require_admin)) -> dict:
    fields = patch.to_fields()
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    _check_parent(system_id, fields.get("parentId"))
    if "parentId" in fields:
        # A human-set parent wins over controller links (db.set_parent_from_source); clearing it
        # hands the decision back to the scan.
        extra = {**(db.get_system(system_id).get("extra") or {})}
        if fields["parentId"]:
            extra["parentSource"] = "manual"
        else:
            extra.pop("parentSource", None)
        fields["extra"] = extra
    system = db.update_system(system_id, {**fields, "confirmed": 1})
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    # Marking a device critical switches monitoring on once (db.update_system); it can be switched off again.
    return {"system": db.get_system(system_id)}


@router.delete("/api/systems/{system_id}")
async def delete_system(system_id: str, withAccounts: bool = False,
                        _: dict = Depends(require_admin)) -> dict:
    """Accounts hold passwords, so a device that still has some is only deleted on explicit
    `?withAccounts=true`; the count is returned, never the accounts themselves."""
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    count = len(db.list_accounts(system_id))
    if count and not withAccounts:
        raise HTTPException(
            status_code=409,
            detail=f"Das Gerät hat {count} Zugang/Zugänge. Zum Löschen withAccounts=true angeben.",
        )
    db.delete_system(system_id)
    return {"ok": True}


@router.post("/api/systems/{system_id}/merge")
async def merge_system(system_id: str, body: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    """Folds another system row into this one -- see db.merge_systems' own docstring for why this
    has to be a human's call (a multi-homed router discovered once per subnet interface, plus
    often a hand-created row for the same box, with no shared MAC across rows to merge on
    automatically)."""
    remove_id = (body.get("removeId") or "").strip()
    if not remove_id:
        raise HTTPException(status_code=400, detail="removeId fehlt.")
    if remove_id == system_id:
        raise HTTPException(status_code=400, detail="Ein Gerät kann nicht mit sich selbst zusammengeführt werden.")
    merged = db.merge_systems(system_id, remove_id)
    if merged is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    return {"system": merged}


# ---------------------------------------------------------------------------------------------
# Authenticated probing (read-only -- see probe_auth)
# ---------------------------------------------------------------------------------------------

_CONTROLLER_LABELS = {"unifi": "UniFi", "proxmox": "Proxmox"}


@router.post("/api/systems/{system_id}/probe")
async def probe_system(system_id: str, _: dict = Depends(require_admin)) -> dict:
    """Reads one device -- the same code and the same settings as the full scan (#135): device
    credentials and the default credential through `pipeline.probe_one_system` (honours
    `scanUseCredentials`), UniFi/Proxmox controller accounts through
    `pipeline.read_controller_account` (honour `scanEnableUnifi`/`scanEnableProxmox`). Which
    controller accounts: the ones attached to or assigned to this device."""
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    settings = db.get_settings()
    accounts = db.list_probe_accounts(system_id)
    if not accounts and probe_auth.fallback_account(settings, system) is None:
        raise HTTPException(status_code=400, detail=(
            "Für dieses Gerät ist kein Zugang freigegeben. Unter Zugänge beim gewünschten Eintrag "
            "„Zum Auslesen verwenden“ aktivieren."
        ))
    controller_categories = pipeline.CONTROLLER_CATEGORIES
    controller_accounts = [a for a in accounts if a.get("category") in controller_categories]
    device_path = not accounts or any(a.get("category") not in controller_categories for a in accounts)

    results: dict = {}
    reasons: list[str] = []
    purpose = ""
    ran = False
    learned_arp: dict[str, str] = {}
    printer_supplies: list[dict] = []

    if device_path:
        if settings.get("scanUseCredentials", True):
            device = await pipeline.probe_one_system(system, settings)
            results.update(device["results"])
            purpose = device["purpose"]
            ran = device["ran"]
            learned_arp, printer_supplies = device["learnedArp"], device["printerSupplies"]
            if not device["ran"] and device["reason"]:
                reasons.append(device["reason"])
        else:
            reasons.append("Auslesen per Zugangsdaten ist in den Einstellungen abgeschaltet")

    scan_subnets: list[str] = []
    if any(a.get("category") == "unifi" for a in controller_accounts):
        scan_subnets = await asyncio.to_thread(
            discovery.effective_subnets, settings, db.list_network_resources(kind="network", active_only=True))
    unifi_synced = False
    for account in controller_accounts:
        category = account["category"]
        name = _CONTROLLER_LABELS[category]
        if not pipeline.controller_enabled(category, settings):
            reasons.append(f"{name}-Abfrage ist in den Einstellungen abgeschaltet")
            continue
        read = await pipeline.read_controller_account(category, account, scan_subnets)
        key = f"{category}:{account['label']}"
        if not read["ok"]:
            results[key] = {"ok": False, "error": read["error"], "facts": {}}
            reasons.append(read["error"])
            continue
        result = read["result"]
        for finding in result["systems"]:
            db.upsert_discovered_system(finding)
        if category == "unifi":
            db.sync_network_resources(account["id"], result["resources"], result["completeScopes"])
            unifi_synced = True
            summary = (f"{len(result['systems'])} Geräte/Clients, "
                       f"{len(result['resources'])} Netzwerkressourcen")
        else:
            summary = f"{len(result['systems'])} Gäste"
        results[key] = {"ok": True, "error": "",
                        "facts": {"synchronisiert": {"label": "Synchronisiert", "value": summary}}}
        ran = True

    if unifi_synced:
        pipeline._link_unifi_topology()
    if learned_arp:
        await pipeline._learn_devices_from_arp(learned_arp, lambda _line: None)
    if printer_supplies:
        pipeline._apply_printer_supplies(printer_supplies, lambda _line: None)

    outcome = {"ran": ran, "results": results, "purpose": purpose,
               "reason": "" if ran else " · ".join(reasons)}
    return {"outcome": outcome, "system": db.get_system(system_id)}


@router.get("/api/systems/{system_id}/config-versions")
async def list_config_versions(system_id: str, _: dict = Depends(require_admin)) -> dict:
    """Admin-only, like the content below: an export can carry SNMP communities, RADIUS secrets and
    WiFi keys, the same class of data as accounts.secretEnc."""
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    return {"versions": db.list_device_config_versions(system_id)}


@router.get("/api/systems/{system_id}/config-versions/{version_id}")
async def get_config_version(system_id: str, version_id: str, _: dict = Depends(require_admin)) -> dict:
    version = db.get_device_config_version(version_id)
    if version is None or version["systemId"] != system_id:
        raise HTTPException(status_code=404, detail="Version nicht gefunden.")
    return {"version": {**version, "content": crypto.decrypt(version["content"])}}


@router.get("/api/systems/{system_id}/errors")
async def list_system_errors(system_id: str, _: dict = Depends(current_user)) -> dict:
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    return {"events": db.list_device_error_events(system_id)}


@router.post("/api/systems/{system_id}/errors/acknowledge")
async def acknowledge_all_system_errors(system_id: str, _: dict = Depends(require_admin)) -> dict:
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    return {"acknowledged": db.acknowledge_device_error_events(system_id)}


@router.post("/api/systems/{system_id}/errors/{event_id}/acknowledge")
async def acknowledge_system_error(system_id: str, event_id: str, _: dict = Depends(require_admin)) -> dict:
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    if not any(e["id"] == event_id for e in db.list_device_error_events(system_id, limit=10_000)):
        raise HTTPException(status_code=404, detail="Ereignis nicht gefunden.")
    db.acknowledge_device_error_events(system_id, event_id)
    return {"ok": True}


@router.get("/api/systems/{system_id}/exposure")
async def system_exposure(system_id: str, _: dict = Depends(current_user)) -> dict:
    if db.get_system(system_id) is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    wan = next((r.get("facts") or {} for r in db.list_network_resources(kind="wan", active_only=True)
                if (r.get("facts") or {}).get("ip")), None)
    data = exposure.build_chains(db.list_exposure_facts(), db.list_systems(), wan)
    return {"entries": exposure.for_system(data, system_id)}


@router.post("/api/systems/{system_id}/classify")
async def classify_system(system_id: str, _: dict = Depends(require_admin)) -> dict:
    """Manual LLM classification of one device (the scan only classifies newly found devices).

    Same rules as the scan (low confidence discarded, source/self-reported names kept); confirmed
    rows only get their empty fields filled. Written via `db.update_system`, not the PATCH handler,
    so `confirmed` is untouched. Deliberately not a tool in `tools.py` (ADR-0004/0011)."""
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    finding = classify.finding_from_system(system)
    if classify.is_container(finding):
        raise HTTPException(status_code=400, detail="Docker-Container werden nicht einzeln eingeordnet.")
    if not finding.get("ip"):
        raise HTTPException(status_code=400, detail="Das Gerät hat keine IP-Adresse.")
    if not classify.has_evidence(finding):
        raise HTTPException(status_code=400, detail=(
            "Für dieses Gerät liegen keine Hinweise vor (Ports, Hersteller, Hostname, mDNS/UPnP, "
            "Web-Banner); eine Einordnung wäre geraten."))
    settings = db.get_settings()
    if not llm_providers.is_configured(settings.get("llmProvider", ""), settings):
        raise HTTPException(status_code=400, detail=(
            "Für den gewählten KI-Anbieter ist kein Zugang eingerichtet (Einstellungen -> KI-Assistent)."))
    by_ip, warnings = await classify.classify([finding], settings, force=True)
    classification = by_ip.get(finding["ip"])
    if classification is None:
        failed = [w for w in warnings if "fehlgeschlagen" in w]
        if failed:
            raise HTTPException(status_code=502, detail=failed[0])
        return {"system": system, "changed": False, "warnings": warnings}
    patch = classify.apply_to_system(system, classification)
    if not patch:
        return {"system": system, "changed": False, "warnings": warnings}
    return {"system": db.update_system(system_id, patch), "changed": True, "warnings": warnings}
