"""Dashboard, first-run setup, access log, monitoring status and the network plan.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import crypto, db, diagnostics, docs, llm_providers, topology
from .. import monitor as monitor_module
from ..deps import current_user, require_admin

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Dashboard + first-run setup
# ---------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------
# Access log, monitoring, overview plan
# ---------------------------------------------------------------------------------------------

@router.get("/api/access-log")
async def access_log(limit: int = 200, action: str | None = None, onlyFailures: bool = False,
                     _: dict = Depends(require_admin)) -> dict:
    return {"entries": db.list_access_log(limit, action, onlyFailures),
            "actions": db.access_log_actions()}


@router.get("/api/monitor")
async def monitor_status(_: dict = Depends(current_user)) -> dict:
    settings = db.get_settings()
    systems = db.list_monitored_systems()
    return {
        "enabled": settings.get("monitorEnabled", True),
        "intervalSeconds": monitor_module.effective_interval(settings),
        "status": monitor_module.monitor.status(),
        "systems": [
            {"id": s["id"], "name": s["name"], "ip": s["ip"], "kind": s["kind"],
             "status": s["status"], "importance": s["importance"], "lastSeen": s["lastSeen"],
             "ports": monitor_module.effective_ports(s)[0],
             "portsExplicit": monitor_module.effective_ports(s)[1],
             "hostOnly": monitor_module.is_host_only(s)}
            for s in systems
        ],
        "events": db.list_monitor_events(limit=50),
    }


@router.post("/api/monitor/run")
async def monitor_run_now(_: dict = Depends(require_admin)) -> dict:
    """Forces one round immediately instead of waiting for the next tick."""
    changes = await monitor_module.monitor.run_once(manual=True)
    return {"changes": changes}


@router.get("/api/topology.svg", response_class=PlainTextResponse)
async def topology_svg(_: dict = Depends(current_user)) -> Response:
    return Response(content=topology.render(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/topology-layer3.svg", response_class=PlainTextResponse)
async def topology_layer3_svg(_: dict = Depends(current_user)) -> Response:
    return Response(content=topology.render_layer3(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.post("/api/diagnostics/dns")
async def dns_diagnostic(body: dict = Body(default={}), _: dict = Depends(current_user)) -> dict:
    settings = db.get_settings()
    names = body.get("names") or settings.get("dnsTestNames") or []
    try:
        return {"result": await diagnostics.dns_check(names)}
    except diagnostics.DiagnosticError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/diagnostics/speedtest")
async def speedtest_diagnostic(_: dict = Depends(current_user)) -> dict:
    try:
        return {"result": await diagnostics.speedtest()}
    except diagnostics.DiagnosticBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "30"}) from exc


@router.get("/api/dashboard")
async def dashboard(_: dict = Depends(current_user)) -> dict:
    systems = db.list_systems()
    settings = db.get_settings()
    scan = db.latest_scan()
    provider = settings.get("llmProvider", "")
    return {
        "homeName": settings.get("homeName"),
        "counts": {
            "total": len(systems),
            "online": sum(1 for s in systems if s["status"] == "online"),
            "critical": sum(1 for s in systems if s["importance"] == "critical"),
            "accounts": len(db.list_accounts()),
        },
        "byKind": {k: sum(1 for s in systems if s["kind"] == k) for k in sorted({s["kind"] for s in systems})},
        "kindLabels": docs.KIND_LABELS,
        "criticalSystems": [
            {**s, "monitorPortsEffective": monitor_module.effective_ports(s)[0]}
            for s in systems if s["importance"] == "critical"
        ][:10],
        "monitorIntervalSeconds": monitor_module.effective_interval(settings),
        "monitorEnabled": settings.get("monitorEnabled", True),
        # Slim on purpose: MEMBER must not get the scan log/summary (issue #119).
        "lastScan": None if scan is None else {k: scan[k] for k in ("startedAt", "finishedAt", "status")},
        "llmConfigured": llm_providers.is_configured(provider, settings),
    }


class SetupSystem(BaseModel):
    name: str
    kind: str = "other"
    ip: str = ""
    location: str = ""
    purpose: str = ""
    url: str = ""
    username: str = ""
    password: str = ""


class SetupAccount(BaseModel):
    label: str
    category: str = "login"
    username: str = ""
    secret: str = ""
    url: str = ""
    notes: str = ""


class SetupBody(BaseModel):
    homeName: str = "Mein Zuhause"
    systems: list[SetupSystem] = Field(default_factory=list)
    accounts: list[SetupAccount] = Field(default_factory=list)
    scanSubnets: list[str] = Field(default_factory=list)


@router.post("/api/setup")
async def run_setup(body: SetupBody, _: dict = Depends(require_admin)) -> dict:
    """Stores what the first-run wizard collected. Each system with a password gets a matching
    account row, so the credential lands encrypted rather than in a free-text note."""
    created_systems = 0
    for entry in body.systems:
        if not entry.name.strip():
            continue
        system = db.create_system({
            "name": entry.name, "kind": entry.kind, "ip": entry.ip, "location": entry.location,
            "purpose": entry.purpose, "url": entry.url, "confirmed": 1, "discovered": 0,
            "importance": "critical" if entry.kind in ("router", "server", "nas", "heating") else "normal",
        })
        created_systems += 1
        if entry.username or entry.password:
            db.create_account({
                "systemId": system["id"], "label": f"Zugang {entry.name}", "category": "login",
                "username": entry.username, "secretEnc": crypto.encrypt(entry.password), "url": entry.url,
            })
    created_accounts = 0
    for account in body.accounts:
        if not account.label.strip():
            continue
        db.create_account({**account.model_dump(exclude={"secret"}),
                           "secretEnc": crypto.encrypt(account.secret)})
        created_accounts += 1

    db.update_settings({"homeName": body.homeName, "setupCompleted": True,
                        "scanSubnets": [s.strip() for s in body.scanSubnets if s.strip()]})
    return {"ok": True, "systems": created_systems, "accounts": created_accounts}
