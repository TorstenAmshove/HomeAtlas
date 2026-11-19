"""Live diagnostics for the UI (the same functions the assistant calls, see diagnostics.py).

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import diagnostics
from ..deps import current_user

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Diagnostics (same functions the assistant calls, exposed for the UI's manual checks)
# ---------------------------------------------------------------------------------------------

class DiagnosticBody(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


@router.post("/api/diagnostics")
async def run_diagnostic(body: DiagnosticBody, _: dict = Depends(current_user)) -> dict:
    handlers = {
        "internet_check": lambda a: diagnostics.internet_check(),
        "ping": lambda a: diagnostics.ping(a.get("host", ""), a.get("count", 3)),
        "check_port": lambda a: diagnostics.check_port(a.get("host", ""), a.get("port", 0)),
        "dns_lookup": lambda a: diagnostics.dns_lookup(a.get("name", "")),
        "http_check": lambda a: diagnostics.http_check(a.get("url", "")),
        "traceroute": lambda a: diagnostics.traceroute(a.get("host", ""), a.get("maxHops", 15)),
    }
    handler = handlers.get(body.tool)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unbekannte Prüfung '{body.tool}'.")
    try:
        return {"result": await handler(body.args)}
    except diagnostics.DiagnosticError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
