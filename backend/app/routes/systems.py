"""Inventory: systems, duplicates/merge/aliases, config versions, device errors, and the
read-only credentialed probe of a single device (see probe_auth).

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from __future__ import annotations
from fastapi import APIRouter, Body, Depends, HTTPException
from .. import (crypto, db, docs, monitor as monitor_module, pipeline, probe_auth,
               unifi_probe)
from ..deps import (_public_account, current_user, require_admin)

router = APIRouter()


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


@router.post("/api/systems")
async def create_system(body: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    # confirmed=1: anything a human typed is protected from being overwritten by the next scan.
    system = db.create_system({**body, "confirmed": 1, "discovered": 0})
    db.ensure_monitoring_for_critical()
    return {"system": db.get_system(system["id"])}


@router.patch("/api/systems/{system_id}")
async def update_system(system_id: str, patch: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    system = db.update_system(system_id, {**patch, "confirmed": 1})
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    # Marking something critical in the UI has to start the monitoring right away, not at the next
    # scan -- that gap is why the dashboard used to show "unbekannt" for the important devices.
    db.ensure_monitoring_for_critical()
    return {"system": db.get_system(system_id)}


@router.delete("/api/systems/{system_id}")
async def delete_system(system_id: str, _: dict = Depends(require_admin)) -> dict:
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
    db.ensure_monitoring_for_critical()
    return {"system": merged}


# ---------------------------------------------------------------------------------------------
# Authenticated probing (read-only -- see probe_auth)
# ---------------------------------------------------------------------------------------------

@router.post("/api/systems/{system_id}/probe")
async def probe_system(system_id: str, _: dict = Depends(require_admin)) -> dict:
    """Runs all read-only probes for one device, including a full UniFi controller sync."""
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    accounts = db.list_probe_accounts(system_id)
    if not accounts:
        raise HTTPException(status_code=400, detail=(
            "Für dieses Gerät ist kein Zugang freigegeben. Unter Zugänge beim gewünschten Eintrag "
            "„Zum Auslesen verwenden“ aktivieren."
        ))
    unifi_accounts = [account for account in accounts if account.get("category") == "unifi"]
    other_accounts = [account for account in accounts if account.get("category") != "unifi"]
    outcome = await probe_auth.probe_system(system, other_accounts) if other_accounts else {
        "ran": False, "results": {}, "purpose": "", "reason": "",
    }
    results = dict(outcome["results"])
    unifi_errors: list[str] = []
    unifi_succeeded = False

    for account in unifi_accounts:
        result = await unifi_probe.probe(
            account.get("url") or "", crypto.decrypt(account.get("secretEnc") or ""),
            account["id"], account.get("systemId"),
        )
        key = f"unifi:{account['label']}"
        if not result["ok"]:
            results[key] = {"ok": False, "error": result["error"], "facts": {}}
            unifi_errors.append(result["error"])
            continue
        for finding in result["systems"]:
            db.upsert_discovered_system(finding)
        db.sync_network_resources(account["id"], result["resources"], result["completeScopes"])
        results[key] = {
            "ok": True,
            "error": "",
            "facts": {"synchronisiert": {
                "label": "Synchronisiert",
                "value": f"{len(result['systems'])} Geräte/Clients, {len(result['resources'])} Netzwerkressourcen",
            }},
        }
        unifi_succeeded = True

    if unifi_succeeded:
        pipeline._link_unifi_topology()
    if outcome["ran"]:
        db.update_system(system_id, {"extra": {**(system.get("extra") or {}),
                                               "probe": probe_auth.without_config_backups(outcome["results"])}})
        if outcome.get("purpose") and not system.get("purpose"):
            db.update_system(system_id, {"purpose": outcome["purpose"]})
        probe_auth.persist_config_backups(system, outcome)
    if unifi_succeeded:
        outcome = {"ran": True, "results": results, "purpose": outcome.get("purpose", ""), "reason": ""}
    elif unifi_errors and not outcome["ran"]:
        outcome = {"ran": False, "results": results, "purpose": outcome.get("purpose", ""),
                   "reason": " · ".join(unifi_errors)}
    else:
        outcome = {**outcome, "results": results}
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
