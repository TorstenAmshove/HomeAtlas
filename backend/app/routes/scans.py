"""Network scans: start, list, status.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from .. import (db, discovery, pipeline)
from ..deps import (_background_tasks, _client, current_user, require_admin)

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------------------------

@router.post("/api/scans")
async def start_scan(request: Request, user: dict = Depends(require_admin)) -> dict:
    if db.running_scan() is not None:
        raise HTTPException(status_code=409, detail="Es läuft bereits ein Scan.")
    ip, agent = _client(request)
    db.log_access("scan.start", user=user, ip=ip, user_agent=agent)
    settings = db.get_settings()
    chosen = discovery.effective_subnets(settings, db.list_network_resources(kind="network", active_only=True))
    scan_id = db.create_scan(", ".join(chosen) or "automatisch")
    task = asyncio.create_task(pipeline.run_full_scan(scan_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"scanId": scan_id}


@router.get("/api/scans")
async def list_scans(_: dict = Depends(current_user)) -> dict:
    return {"scans": db.list_scans(), "running": db.running_scan()}


@router.get("/api/scans/{scan_id}")
async def get_scan(scan_id: str, _: dict = Depends(current_user)) -> dict:
    scan = db.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden.")
    return {"scan": scan}
