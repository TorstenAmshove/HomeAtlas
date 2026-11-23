"""Write-capable device administration, admin-only (ADR-0002): SSH keys, interactive consoles,
local and remote Docker control, Proxmox, reboot, Shelly/Home-Assistant switches. Never imported by
tools.py, mcp_server.py or pipeline.py.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import crypto, db, docker_admin, probe_auth, proxmox_admin, proxmox_probe, remote_admin, switch_admin
from ..deps import _client, _public_account, _ws_authenticate, _ws_client, require_admin

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# SSH key generation/distribution and interactive consoles (see remote_admin.py) -- write-capable,
# admin-only, never reachable from tools.py/the chat assistant. A human clicking a button in the
# browser is the only caller any of this has.
# ---------------------------------------------------------------------------------------------

class GenerateKeyBody(BaseModel):
    label: str = "SSH-Schlüssel (HomeAtlas)"


@router.post("/api/systems/{system_id}/ssh-keys")
async def generate_ssh_key(system_id: str, body: GenerateKeyBody, request: Request,
                           user: dict = Depends(require_admin)) -> dict:
    """Generates a new keypair and stores it as an ordinary `sshkey`-category account -- the
    public line lives in the account's `notes` field (already unmasked by `_public_account`), so
    no new field or reveal endpoint is needed to see it."""
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    private_pem, public_line = remote_admin.generate_keypair(comment=f"homeatlas@{system['name']}")
    account = db.create_account({
        "systemId": system_id, "label": body.label, "category": "sshkey", "username": "",
        "secretEnc": crypto.encrypt(private_pem), "passphraseEnc": crypto.encrypt(""),
        "url": "", "notes": public_line, "allowProbe": False, "port": 22,
    })
    ip, agent = _client(request)
    db.log_access("sshkey.generate", user=user, ip=ip, user_agent=agent, detail=system["name"])
    return {"account": _public_account(account), "publicKey": public_line}


class DeployKeyBody(BaseModel):
    loginAccountId: str
    port: int = 0


@router.post("/api/accounts/{account_id}/deploy")
async def deploy_ssh_key(account_id: str, body: DeployKeyBody, request: Request,
                         user: dict = Depends(require_admin)) -> dict:
    """Installs an already-generated key's public half on its device, authenticating with a
    *different*, already-trusted credential (`loginAccountId`) -- see remote_admin.deploy_public_key
    for the read-modify-write mechanics."""
    key_account = db.get_account(account_id)
    if key_account is None or key_account.get("category") != "sshkey":
        raise HTTPException(status_code=404, detail="SSH-Schlüssel nicht gefunden.")
    login_account = db.get_account(body.loginAccountId)
    if login_account is None:
        raise HTTPException(status_code=404, detail="Login-Zugang nicht gefunden.")
    if login_account.get("systemId") != key_account.get("systemId"):
        raise HTTPException(status_code=400, detail="Der Login-Zugang gehört zu einem anderen Gerät.")
    system = db.get_system(key_account["systemId"]) if key_account.get("systemId") else None
    if system is None:
        raise HTTPException(status_code=400, detail="Der Schlüssel ist keinem Gerät zugeordnet.")
    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Für dieses Gerät ist keine Adresse hinterlegt.")

    # Derived from the stored private key, not taken from the editable `notes` field (#47).
    try:
        public_line = remote_admin.public_line_for(
            crypto.decrypt(key_account.get("secretEnc") or ""),
            crypto.decrypt(key_account.get("passphraseEnc") or ""),
            comment=f"homeatlas@{system['name']}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await remote_admin.deploy_public_key(host, login_account, public_line, port=body.port)
    ip, agent = _client(request)
    db.log_access("sshkey.deploy", user=user, ip=ip, user_agent=agent, ok=result["ok"],
                  detail=f"{system['name']} über {login_account['label']}")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True, "changed": result["changed"]}


def _ssh_eligible(account: dict) -> bool:
    """Same eligibility test probe_auth.probe_system's SSH branch already uses. Deliberately NOT
    gated on `allowProbe`: that flag's own docstring scopes it to the read-only auto-probe
    feature specifically -- reusing it here would conflate two different consents an admin gave
    for two different reasons."""
    return account.get("category") == "sshkey" or (
        account.get("category") == "login" and (account.get("port") or 0) in (22, 0)
    )


@router.websocket("/api/ws/systems/{system_id}/ssh-console")
async def ssh_console(websocket: WebSocket, system_id: str) -> None:
    user = await _ws_authenticate(websocket)
    if user is None:
        await websocket.close(code=1008)
        return
    account_id = websocket.query_params.get("accountId", "")
    system, account = db.get_system(system_id), db.get_account(account_id)
    if system is None or account is None or account.get("systemId") != system_id or not _ssh_eligible(account):
        await websocket.close(code=1008)
        return

    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    ip, agent = _ws_client(websocket)
    started = time.monotonic()
    try:
        connection, process = await remote_admin.open_ssh_pty(host, account)
    except Exception as exc:  # noqa: BLE001 -- reported to the client, connection setup can fail
        # in many ways (auth, network, host down) and all of them are just "console unavailable".
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        db.log_access("console.ssh.open", user=user, ip=ip, user_agent=agent, ok=False,
                      detail=f"{system['name']}: {exc}")
        return

    db.log_access("console.ssh.open", user=user, ip=ip, user_agent=agent, detail=system["name"])
    try:
        await _relay_terminal(websocket, read=process.stdout.read, write=process.stdin.write,
                              resize=process.change_terminal_size)
    finally:
        process.close()
        connection.close()
        db.log_access("console.ssh.close", user=user, ip=ip, user_agent=agent,
                      detail=f"{system['name']} ({round(time.monotonic() - started)}s)")


async def _relay_terminal(websocket: WebSocket, *, read, write, resize) -> None:
    """Binary WS frames = raw terminal bytes, unmodified, both directions. Text WS frames = JSON
    control messages -- browser to server `{"type":"resize","cols":n,"rows":n}`, server to browser
    `{"type":"exit"}` once the process reached EOF. Two concurrent
    tasks; either one finishing (EOF from the process, or the browser disconnecting) tears down
    both, which unwinds the `finally` blocks in the caller and closes the underlying session."""
    async def from_client() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is not None:
                write(data)
                continue
            text = message.get("text")
            if text is None:
                continue
            try:
                control = json.loads(text)
            except ValueError:
                continue
            if control.get("type") == "resize":
                maybe_awaitable = resize(int(control.get("cols", 80)), int(control.get("rows", 24)))
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable

    async def from_process() -> None:
        while True:
            data = await read(4096)
            if not data:
                # EOF: tell the browser the session ended. The client may already be gone; the
                # session is torn down right after either way.
                try:
                    await websocket.send_json({"type": "exit"})
                except Exception:
                    pass
                return
            await websocket.send_bytes(data)

    tasks = [asyncio.create_task(from_client()), asyncio.create_task(from_process())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------------------------
# Docker container control (see docker_admin.py) -- write-capable, admin-only, same posture as
# the SSH console section above. Local containers only; see remote_admin.py for containers on
# other hosts, reached over SSH.
# ---------------------------------------------------------------------------------------------

def _container_id(system: dict) -> str:
    return ((system.get("extra") or {}).get("docker") or {}).get("containerId", "")


_CONTAINER_ACTIONS = {
    "start": docker_admin.start_container,
    "stop": docker_admin.stop_container,
    "restart": docker_admin.restart_container,
}


@router.post("/api/systems/{system_id}/container/{action}")
async def container_action(system_id: str, action: str, request: Request,
                           user: dict = Depends(require_admin)) -> dict:
    if action not in _CONTAINER_ACTIONS:
        raise HTTPException(status_code=404, detail="Unbekannte Aktion.")
    system = db.get_system(system_id)
    if system is None or system.get("kind") != "container":
        raise HTTPException(status_code=404, detail="Container nicht gefunden.")
    container_id = _container_id(system)
    if not container_id:
        raise HTTPException(status_code=400, detail="Keine Container-ID hinterlegt -- bitte erneut scannen.")

    result = await _CONTAINER_ACTIONS[action](container_id)
    ip, agent = _client(request)
    db.log_access(f"container.{action}", user=user, ip=ip, user_agent=agent, ok=result["ok"], detail=system["name"])
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


@router.get("/api/systems/{system_id}/container/logs")
async def container_logs(system_id: str, tail: int = 200, _: dict = Depends(require_admin)):
    system = db.get_system(system_id)
    if system is None or system.get("kind") != "container":
        raise HTTPException(status_code=404, detail="Container nicht gefunden.")
    container_id = _container_id(system)
    if not container_id:
        raise HTTPException(status_code=400, detail="Keine Container-ID hinterlegt -- bitte erneut scannen.")
    return StreamingResponse(docker_admin.stream_logs(container_id, tail), media_type="text/plain")


@router.websocket("/api/ws/systems/{system_id}/docker-console")
async def docker_console(websocket: WebSocket, system_id: str) -> None:
    user = await _ws_authenticate(websocket)
    if user is None:
        await websocket.close(code=1008)
        return
    system = db.get_system(system_id)
    container_id = _container_id(system) if system else ""
    if system is None or system.get("kind") != "container" or not container_id:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    ip, agent = _ws_client(websocket)
    started = time.monotonic()
    try:
        session = await docker_admin.open_exec_session(container_id)
    except Exception as exc:  # noqa: BLE001 -- reported to the client; many ways this can fail
        # (container has no shell, container gone, socket error) and all are "console unavailable".
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        db.log_access("console.docker.open", user=user, ip=ip, user_agent=agent, ok=False,
                      detail=f"{system['name']}: {exc}")
        return

    db.log_access("console.docker.open", user=user, ip=ip, user_agent=agent, detail=system["name"])
    try:
        await _relay_terminal(websocket, read=session.read, write=session.write, resize=session.resize)
    finally:
        session.close()
        db.log_access("console.docker.close", user=user, ip=ip, user_agent=agent,
                      detail=f"{system['name']} ({round(time.monotonic() - started)}s)")


# ---------------------------------------------------------------------------------------------
# Remote Docker control (see remote_admin.py) -- same posture as the local section above, for
# containers on a host other than the one HomeAtlas itself runs on, reached over SSH with a
# stored credential. `accountId` is always required and re-validated per request (never trusted
# from a prior call) -- same eligibility test as the SSH console.
# ---------------------------------------------------------------------------------------------

def _remote_host_and_account(system_id: str, account_id: str) -> tuple[dict, dict, str]:
    system, account = db.get_system(system_id), db.get_account(account_id)
    if system is None or account is None or account.get("systemId") != system_id or not _ssh_eligible(account):
        raise HTTPException(status_code=404, detail="Gerät oder Zugang nicht gefunden.")
    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Für dieses Gerät ist keine Adresse hinterlegt.")
    return system, account, host


def _proxmox_account(system_id: str) -> dict | None:
    """The "proxmox"-category account attached to this system, if any -- the same signal
    proxmox_probe.py/pipeline.py already treat as "this system row IS the Proxmox host" (see
    AccountsPage.tsx's own hint to attach that credential to the host itself). Used to route
    `list_remote_containers` and its action/console/logs counterparts to the pct/qm/REST path
    instead of Docker -- a Proxmox host has no Docker CLI at all, see remote_admin.list_remote_
    proxmox_guests' docstring for the bug this avoids."""
    return next((a for a in db.list_accounts(system_id) if a.get("category") == "proxmox"), None)


def _parse_proxmox_guest_id(container_id: str) -> tuple[str, str, str] | None:
    """(node, kind, vmid) from a container_id in either the REST-sourced "{node}:{qemu|lxc}:
    {vmid}" shape (proxmox_probe.list_guests) or the SSH-sourced "{qemu|lxc}:{vmid}" shape
    (remote_admin._parse_pct_list/_parse_qm_list, which never learns the node's own name). ":" not
    "/" -- container_id is a single FastAPI path segment (`{container_id}` below), and a literal
    slash inside it would split into extra segments and break routing. `kind` here matches
    proxmox_probe's/proxmox_admin's own vocabulary ("vm"/"container"), not the raw API path
    segment. `node` is "" when unknown -- callers that need it (REST actions, the task log) must
    check for that themselves and fall back or fail accordingly."""
    parts = container_id.split(":")
    if len(parts) == 3:
        node, path, vmid = parts
    elif len(parts) == 2:
        node, path, vmid = "", parts[0], parts[1]
    else:
        return None
    kind = {"qemu": "vm", "lxc": "container"}.get(path)
    if kind is None or not vmid.isdigit():
        return None
    return node, kind, vmid


@router.get("/api/systems/{system_id}/remote-containers")
async def list_remote_containers(system_id: str, accountId: str = "", _: dict = Depends(require_admin)) -> dict:
    proxmox_account = _proxmox_account(system_id)
    if proxmox_account is not None:
        token_id = proxmox_account.get("username") or ""
        token_secret = crypto.decrypt(proxmox_account.get("secretEnc") or "")
        result = await proxmox_probe.list_guests(proxmox_account.get("url") or "", token_id, token_secret)
        if not result["ok"] and accountId:
            # REST unreachable/misconfigured -- fall back to the native pct/qm CLI over SSH rather
            # than ever trying the generic Docker path below, which does not exist on this host.
            _system, account, host = _remote_host_and_account(system_id, accountId)
            result = await remote_admin.list_remote_proxmox_guests(host, account)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result["error"])
        # proxmoxUrl lets the frontend build a link straight into Proxmox's own noVNC web console
        # (?console=kvm|lxc&node=&vmid=) -- HomeAtlas never proxies that console itself.
        return {"containers": result["containers"], "proxmoxUrl": proxmox_account.get("url") or ""}

    _system, account, host = _remote_host_and_account(system_id, accountId)
    result = await remote_admin.list_remote_containers(host, account)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"containers": result["containers"], "proxmoxUrl": ""}


@router.post("/api/systems/{system_id}/remote-containers/{container_id}/{action}")
async def remote_container_action(system_id: str, container_id: str, action: str, accountId: str,
                                  request: Request, user: dict = Depends(require_admin)) -> dict:
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=404, detail="Unbekannte Aktion.")
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")

    proxmox_account = _proxmox_account(system_id)
    if proxmox_account is not None:
        parsed = _parse_proxmox_guest_id(container_id)
        if parsed is None:
            raise HTTPException(status_code=400, detail="Ungültige Container-/VM-ID.")
        node, kind, vmid = parsed
        result = None
        if node:
            token_id = proxmox_account.get("username") or ""
            token_secret = crypto.decrypt(proxmox_account.get("secretEnc") or "")
            result = await proxmox_admin.guest_action(
                proxmox_account.get("url") or "", token_id, token_secret, node, kind, vmid, action)
        if (result is None or not result["ok"]) and accountId:
            # REST unreachable/misconfigured (or no node known -- an SSH-sourced listing) -- fall
            # back to the native pct/qm CLI over SSH, same posture as the listing route above.
            _system, account, host = _remote_host_and_account(system_id, accountId)
            result = await remote_admin.run_remote_proxmox_guest_command(host, account, kind, vmid, action)
        if result is None:
            raise HTTPException(status_code=400, detail=(
                "Proxmox-API nicht erreichbar und kein SSH-Zugang für den Ausweich-Befehl ausgewählt."))
        ip, agent = _client(request)
        db.log_access(f"container.proxmox.{action}", user=user, ip=ip, user_agent=agent, ok=result["ok"],
                      detail=f"{system['name']}: {container_id}")
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"ok": True}

    _system, account, host = _remote_host_and_account(system_id, accountId)
    result = await remote_admin.run_remote_docker_command(host, account, action, container_id)
    ip, agent = _client(request)
    db.log_access(f"container.remote.{action}", user=user, ip=ip, user_agent=agent, ok=result["ok"],
                  detail=f"{system['name']}: {container_id[:12]}")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


@router.get("/api/systems/{system_id}/remote-containers/{container_id}/logs")
async def remote_container_logs(system_id: str, container_id: str, accountId: str = "", mode: str = "",
                                _: dict = Depends(require_admin)) -> dict:
    """Text-based logs for one remote Docker container or Proxmox guest -- a one-shot fetch (last
    N lines / a task history), not a live tail, so this is a plain GET returning JSON rather than
    a websocket relay like the console routes above.

    For a Proxmox guest, `mode` picks the source: "journal" runs `journalctl` inside an LXC
    container over SSH (real system-log lines, LXC-only -- see remote_admin.run_remote_lxc_
    journalctl); anything else (the default) reads Proxmox's own REST task history for the guest
    (proxmox_probe.guest_task_log), which needs `node` to be known and therefore only works for
    guests the REST listing itself returned, not ones only discovered via the SSH pct/qm fallback."""
    proxmox_account = _proxmox_account(system_id)
    if proxmox_account is not None:
        parsed = _parse_proxmox_guest_id(container_id)
        if parsed is None:
            raise HTTPException(status_code=400, detail="Ungültige Container-/VM-ID.")
        node, kind, vmid = parsed
        if mode == "journal":
            if kind != "container":
                raise HTTPException(status_code=400, detail="journalctl ist nur für LXC-Container verfügbar.")
            if not accountId:
                raise HTTPException(status_code=400, detail="Für journalctl wird ein SSH-Zugang benötigt.")
            _system, account, host = _remote_host_and_account(system_id, accountId)
            result = await remote_admin.run_remote_lxc_journalctl(host, account, vmid)
        else:
            if not node:
                raise HTTPException(status_code=400, detail=(
                    "Das Aufgabenprotokoll ist nur über die Proxmox-API verfügbar -- dieser Gast wurde "
                    "nur über den SSH-Ausweichweg gefunden, der den Node-Namen nicht kennt."
                ))
            token_id = proxmox_account.get("username") or ""
            token_secret = crypto.decrypt(proxmox_account.get("secretEnc") or "")
            result = await proxmox_probe.guest_task_log(
                proxmox_account.get("url") or "", token_id, token_secret, node, vmid)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"text": result["text"]}

    _system, account, host = _remote_host_and_account(system_id, accountId)
    result = await remote_admin.remote_container_logs(host, account, container_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"text": result["text"]}


@router.post("/api/systems/{system_id}/reboot")
async def reboot_system(system_id: str, accountId: str, request: Request,
                        user: dict = Depends(require_admin)) -> dict:
    """Reboots the device itself (not a Docker container or Proxmox guest -- those have their own,
    more specific restart actions above). Two paths, chosen by what the device is: a FRITZ!Box or
    other TR-064 router reboots over its own management HTTP port with the "login" credential
    already used for its read-only GetInfo probe (see probe_auth.probe_fritzbox); anything else
    needs an SSH-eligible credential and gets a generic Linux `reboot`. Routers essentially never
    run SSH and Linux hosts essentially never speak TR-064, so this is a real either/or, not an
    arbitrary priority order."""
    system, account = db.get_system(system_id), db.get_account(accountId)
    if system is None or account is None or account.get("systemId") != system_id:
        raise HTTPException(status_code=404, detail="Gerät oder Zugang nicht gefunden.")
    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Für dieses Gerät ist keine Adresse hinterlegt.")

    is_fritzbox = "fritz" in " ".join(
        [system.get("vendor", ""), system.get("model", ""), system.get("name", "")]
    ).lower()
    if is_fritzbox or system.get("kind") == "router":
        if account.get("category") not in ("login", "router"):
            raise HTTPException(status_code=400, detail=(
                "Für einen Router-Neustart wird der TR-064-Zugang (Kategorie „Login“) benötigt."))
        result = await remote_admin.reboot_fritzbox(host, account)
    else:
        if not _ssh_eligible(account):
            raise HTTPException(status_code=400, detail="Für einen Neustart wird ein SSH-Zugang benötigt.")
        result = await remote_admin.reboot_host(host, account)

    ip, agent = _client(request)
    db.log_access("system.reboot", user=user, ip=ip, user_agent=agent, ok=result["ok"], detail=system["name"])
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# Smart-Home-Schalten (Shelly-Relais direkt, Home-Assistant-Entities über deren REST-API) -- see
# switch_admin.py's module docstring for why this write module, unlike every other one, is also
# reachable from the chat assistant (tools.py's `set_switch`), not just these UI-triggered routes.
# ---------------------------------------------------------------------------------------------

@router.post("/api/systems/{system_id}/shelly-switch/{action}")
async def shelly_switch(system_id: str, action: str, request: Request, channel: int = Query(0, ge=0, le=switch_admin.SHELLY_MAX_CHANNEL),
                        user: dict = Depends(require_admin)) -> dict:
    if action not in ("on", "off"):
        raise HTTPException(status_code=404, detail="Unbekannte Aktion.")
    system = db.get_system(system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
    if not switch_admin.is_shelly(system):
        raise HTTPException(status_code=400, detail="Dieses Gerät ist kein Shelly.")
    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Für dieses Gerät ist keine Adresse hinterlegt.")

    result = await switch_admin.shelly_set_switch(host, action == "on", channel)
    ip, agent = _client(request)
    db.log_access("switch.shelly", user=user, ip=ip, user_agent=agent, ok=result["ok"],
                  detail=f"{system['name']} -> {action}")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


@router.get("/api/systems/{system_id}/ha-switchables")
async def ha_switchables(system_id: str, accountId: str, _: dict = Depends(require_admin)) -> dict:
    system, account = db.get_system(system_id), db.get_account(accountId)
    if system is None or account is None or account.get("systemId") != system_id or account.get("category") != "homeassistant":
        raise HTTPException(status_code=404, detail="Gerät oder Home-Assistant-Zugang nicht gefunden.")
    result = await probe_auth.list_ha_switchables(account.get("url") or system.get("url") or "", account)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"entities": result["entities"]}


@router.post("/api/systems/{system_id}/ha-switch/{action}")
async def ha_switch(system_id: str, action: str, accountId: str, entityId: str, request: Request,
                    user: dict = Depends(require_admin)) -> dict:
    if action not in ("on", "off"):
        raise HTTPException(status_code=404, detail="Unbekannte Aktion.")
    system, account = db.get_system(system_id), db.get_account(accountId)
    if system is None or account is None or account.get("systemId") != system_id or account.get("category") != "homeassistant":
        raise HTTPException(status_code=404, detail="Gerät oder Home-Assistant-Zugang nicht gefunden.")

    token = crypto.decrypt(account.get("secretEnc") or "")
    result = await switch_admin.ha_set_switch(account.get("url") or system.get("url") or "", token, entityId, action == "on")
    ip, agent = _client(request)
    db.log_access("switch.ha", user=user, ip=ip, user_agent=agent, ok=result["ok"],
                  detail=f"{entityId} -> {action}")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


@router.websocket("/api/ws/systems/{system_id}/remote-docker-console")
async def remote_docker_console(websocket: WebSocket, system_id: str) -> None:
    user = await _ws_authenticate(websocket)
    if user is None:
        await websocket.close(code=1008)
        return
    account_id = websocket.query_params.get("accountId", "")
    container_id = websocket.query_params.get("containerId", "")
    system, account = db.get_system(system_id), db.get_account(account_id)
    if (system is None or account is None or account.get("systemId") != system_id
            or not _ssh_eligible(account) or not container_id or _proxmox_account(system_id) is not None):
        await websocket.close(code=1008)
        return
    host = (system.get("ip") or system.get("hostname") or "").strip()
    if not host:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    ip, agent = _ws_client(websocket)
    started = time.monotonic()
    try:
        connection, process = await remote_admin.open_remote_docker_exec(host, account, container_id)
    except Exception as exc:  # noqa: BLE001 -- reported to the client, connection setup can fail
        # in many ways (auth, network, host down, no docker on remote) -- all "console unavailable".
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        db.log_access("console.remote-docker.open", user=user, ip=ip, user_agent=agent, ok=False,
                      detail=f"{system['name']}: {exc}")
        return

    db.log_access("console.remote-docker.open", user=user, ip=ip, user_agent=agent, detail=system["name"])
    try:
        await _relay_terminal(websocket, read=process.stdout.read, write=process.stdin.write,
                              resize=process.change_terminal_size)
    finally:
        process.close()
        connection.close()
        db.log_access("console.remote-docker.close", user=user, ip=ip, user_agent=agent,
                      detail=f"{system['name']} ({round(time.monotonic() - started)}s)")
