"""FastAPI application: auth, inventory, accounts, documentation, scans, and the assistant.

Two cross-cutting rules the routes below implement consistently:

* **Secrets leave the server only on explicit, per-item request.** API keys come back from
  `GET /api/settings` masked, and a stored password is returned only by
  `GET /api/accounts/{id}/secret` -- an admin-only route that fetches exactly one secret. Nothing
  bulk-returns plaintext, so an over-broad frontend fetch can't leak the credential store.
* **MEMBER is a real read-only role.** It exists so the household can look things up and use the
  troubleshooting chat without also getting the router password; `require_admin` guards every
  mutating and every secret-revealing route -- with one deliberate exception: the chat assistant's
  `set_switch` tool (see `tools.py`) lets any authenticated role, and any external MCP client, turn
  a known switch/light on or off or move a shutter (never a garage door/gate, ADR-0013). That's a scoped, explicit product decision (see `switch_admin.py`
  and `tools.py`'s module docstrings), not an oversight -- the direct REST routes below
  (`/shelly-switch`, `/ha-switch`) stay admin-gated like everything else.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import (auth, crypto, db, mcp_server, monitor as monitor_module, pipeline)
from . import routes
from .deps import logger
from .version import app_version
from .routes.settings import _migrate_plaintext_secrets

# Re-exported for tests and anything that used to import them from here: these are the very
# objects the routes depend on, so `app.dependency_overrides[main.current_user]` keeps working.
from .deps import _ws_authenticate, current_user, require_admin  # noqa: E402,F401
from .routes.remote import _proxmox_account  # noqa: E402,F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    _migrate_plaintext_secrets()
    db.abandon_stale_scans()
    bootstrap = auth.ensure_admin_bootstrapped()
    generated = bootstrap.password
    if bootstrap.reason:
        logger.warning(
            "ADMIN_PASSWORD erfuellt die Passwortrichtlinie nicht (%s) -- es wurde ein Passwort generiert.",
            bootstrap.reason,
        )
    if generated:
        logger.warning(
            "=" * 72 + "\nHomeAtlas: Erster Start. Anmeldedaten:\n"
            "  Benutzer:  %s\n  Passwort:  %s\n"
            "Dieses Passwort wird nur EINMAL angezeigt. Bitte notieren und nach dem Login\n"
            "unter Einstellungen -> Konto aendern.\n" + "=" * 72,
            os.environ.get("ADMIN_USERNAME", "admin"), generated,
        )
    monitor_module.monitor.start()
    pipeline.scheduler.start()
    # The MCP session manager needs its task group alive for the app's whole lifetime, same as
    # the monitor above -- see mcp_server.py.
    async with mcp_server.session_manager.run():
        try:
            yield
        finally:
            await monitor_module.monitor.stop()
            await pipeline.scheduler.stop()


app = FastAPI(title="HomeAtlas", version=app_version(), lifespan=lifespan)
app.mount("/api/mcp", mcp_server.asgi_app)


@app.exception_handler(crypto.SecretUnreadable)
async def _secret_unreadable_handler(_request, exc: crypto.SecretUnreadable):
    """Any route that uses a stored secret and can't decrypt it answers 409 -- never proceeds with
    an empty password (#118). The message carries no token or plaintext."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})

# One router per capability group (see docs/specs/README.md). Order matters only where two
# routes could match the same path; it is the order the routes had in this file before the split.
for _routes in (routes.auth, routes.settings, routes.systems, routes.accounts, routes.remote, routes.docs,
                routes.scans, routes.diagnostics, routes.chat, routes.overview):
    app.include_router(_routes.router)
