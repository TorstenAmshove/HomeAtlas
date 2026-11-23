"""Live diagnostics for the UI (the same functions the assistant calls, see diagnostics.py).

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import diagnostics
from ..deps import current_user
from ..limits import SlidingWindowLimiter

router = APIRouter()

# Traceroutes are slow; cap them per user (the global concurrency cap lives in diagnostics.py).
# Invalid hosts count too, so a bad input can't be used to probe without limit.
_TRACEROUTE_LIMITER = SlidingWindowLimiter(3, 60)


# ---------------------------------------------------------------------------------------------
# Diagnostics (same functions the assistant calls, exposed for the UI's manual checks)
# ---------------------------------------------------------------------------------------------

class DiagnosticBody(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


@router.post("/api/diagnostics")
async def run_diagnostic(body: DiagnosticBody, user: dict = Depends(current_user)) -> dict:
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
    if body.tool == "traceroute":
        allowed, retry_after = _TRACEROUTE_LIMITER.allow(user["id"])
        if not allowed:
            raise HTTPException(status_code=429, headers={"Retry-After": str(retry_after)},
                                detail="Zu viele Traceroutes. Bitte kurz warten und noch einmal versuchen.")
    try:
        return {"result": await handler(body.args)}
    except diagnostics.DiagnosticBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "10"}) from exc
    except diagnostics.DiagnosticError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
