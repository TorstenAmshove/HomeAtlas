"""Live, read-only access to the Proxmox VE API for the assistant (ADR-0021).

Why a separate module: `proxmox_probe.py` belongs to the scan pipeline and stores what it finds;
this module answers one question at a time ("why is VM X slow?", "did the backup run?") and stores
nothing. It deliberately duplicates the little HTTP code it needs instead of importing
`proxmox_probe` (scan and live reads stay independently changeable, nobody can widen one by editing
the other). It must never import a `*_admin` module or a scan module, and nothing but `tools.py`
may import it (tests/test_proxmox_live.py checks both).

Rules enforced here:
* Auth is the API token (`Authorization: PVEAPIToken=<id>=<secret>`), the same one the scan uses.
  Recommended role: PVEAuditor -- HomeAtlas cannot check the token's rights, so the allowlist below
  is the actual barrier, not the token.
* `_request` is the single network access. Only GET on the fixed paths in `_ALLOWED`; the only
  caller-controlled path parts are validated (node name, qemu|lxc, vmid, hour|day). Query strings
  are built here from internal values. No redirects, no retries.
* Responses pass a per-object **allowlist of fields**. Free text of a guest (`description`, tags,
  config) is never requested, task **log lines and UPIDs are never returned**. Key-name redaction
  and removal of the plaintext secret from strings is only the second layer.
* Errors are `ProxmoxLiveError` with fixed German texts -- never a response body, URL or token.
"""
from __future__ import annotations

import json
import math
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_NODE = re.compile(r"^[A-Za-z0-9-]{1,64}\Z")
_VMID = re.compile(r"^[0-9]{1,9}\Z")
_BASE = "/api2/json"
# name -> path template. The only requests this module can ever send (all GET).
_ALLOWED: dict[str, str] = {
    "nodes": _BASE + "/nodes",
    "node_status": _BASE + "/nodes/{node}/status",
    "node_rrd": _BASE + "/nodes/{node}/rrddata",
    "node_tasks": _BASE + "/nodes/{node}/tasks",
    "guest_list": _BASE + "/nodes/{node}/{kind}",
    "guest_status": _BASE + "/nodes/{node}/{kind}/{vmid}/status/current",
    "guest_rrd": _BASE + "/nodes/{node}/{kind}/{vmid}/rrddata",
}
_KINDS = ("qemu", "lxc")
TIMEFRAMES = ("hour", "day")
MAX_ENTRIES = 20
MAX_TASKS = 10
MAX_POINTS = 12
MAX_CHARS = 16000
MAX_TEXT = 200
_MAX_BODY = 8_000_000
_MIN_SECRET = 8

# Test hook: an httpx transport replacing the network.
_transport: httpx.AsyncBaseTransport | None = None

GUEST_FIELDS = ("name", "vmid", "status", "qmpstatus", "uptime", "lock", "cpu", "cpus", "mem", "maxmem", "disk",
                "maxdisk", "netin", "netout", "diskread", "diskwrite")
NODE_FIELDS = ("status", "uptime", "cpu")
TASK_FIELDS = ("type", "status", "starttime", "endtime", "user")
GUEST_RRD = ("cpu", "mem", "maxmem", "disk", "maxdisk", "netin", "netout", "diskread", "diskwrite")
NODE_RRD = ("cpu", "iowait", "loadavg", "memused", "memtotal", "rootused", "roottotal", "netin", "netout")
_SECRET_KEY = re.compile(r"key|token|secret|password|psk|^x_", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ProxmoxLiveError(Exception):
    """Carries a fixed, secret-free German message for the user/model."""


def valid_node(node: object) -> str:
    if not isinstance(node, str) or not _NODE.match(node):
        raise ValueError("Ungültiger Node-Name.")
    return node


def valid_vmid(vmid: object) -> str:
    if isinstance(vmid, bool) or not isinstance(vmid, (int, str)) or not _VMID.match(str(vmid)):
        raise ValueError("Ungültige VMID.")
    return str(int(vmid))


def valid_timeframe(value: object) -> str:
    text = "hour" if value in (None, "") else value
    if text not in TIMEFRAMES:
        raise ProxmoxLiveError("Ungültiger timeframe (erlaubt: hour, day).")
    return text  # type: ignore[return-value]


def _clean_text(value: str, secret: str) -> str:
    text = _CONTROL.sub(" ", value)
    if secret:
        text = text.replace(secret, "[entfernt]")
    return text[:MAX_TEXT]


def redact(value: object, secret: str = "") -> object:
    """Second layer: drops secret-looking keys, strips control characters and the plaintext secret."""
    if isinstance(value, dict):
        return {k: redact(v, secret) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, str):
        return _clean_text(value, secret)
    return value


async def _request(name: str, base_url: str, token_id: str, secret: str, *, node: str | None = None,
                   kind: str | None = None, vmid: object = None, timeframe: str | None = None,
                   limit: int | None = None, for_vmid: object = None) -> object:
    template = _ALLOWED.get(name)
    if template is None:
        raise ValueError(f"Endpunkt nicht in der Allowlist: {name}")
    parts: dict[str, str] = {}
    if "{node}" in template:
        parts["node"] = valid_node(node)
    if "{kind}" in template:
        if kind not in _KINDS:
            raise ValueError("Ungültiger Gast-Typ.")
        parts["kind"] = kind
    if "{vmid}" in template:
        parts["vmid"] = valid_vmid(vmid)
    path = template.format(**parts)
    query: list[str] = []
    if name.endswith("_rrd"):
        query = [f"timeframe={valid_timeframe(timeframe)}", "cf=AVERAGE"]
    elif name == "node_tasks":
        query = [f"limit={max(1, min(MAX_TASKS, int(limit or MAX_TASKS)))}"]
        if for_vmid is not None:
            query.append(f"vmid={valid_vmid(for_vmid)}")
    if not (base_url or "").strip():
        raise ProxmoxLiveError("Für den Proxmox-Zugang ist keine URL hinterlegt.")
    if not (token_id or "").strip() or len(secret or "") < _MIN_SECRET:
        raise ProxmoxLiveError("Proxmox-Zugang unvollständig konfiguriert (Token-ID oder Secret fehlt).")
    url = base_url.strip().rstrip("/") + path + ("?" + "&".join(query) if query else "")
    headers = {"Authorization": f"PVEAPIToken={token_id}={secret}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, follow_redirects=False, headers=headers,
                                     transport=_transport) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        raise ProxmoxLiveError("Der Proxmox-Host antwortet nicht rechtzeitig.") from None
    except httpx.HTTPError:
        raise ProxmoxLiveError("Der Proxmox-Host ist nicht erreichbar.") from None
    status = response.status_code
    if 300 <= status < 400:
        raise ProxmoxLiveError("Der Proxmox-Host leitet weiter; die Adresse im Zugang prüfen.")
    if status in (401, 403):
        raise ProxmoxLiveError("Der Proxmox-Host verweigert den Zugriff (API-Token prüfen; empfohlen: Rolle PVEAuditor).")
    if status in (404, 405):
        raise ProxmoxLiveError("Dieser Endpunkt ist auf diesem Proxmox-Host nicht verfügbar.")
    if status == 429:
        raise ProxmoxLiveError("Der Proxmox-Host begrenzt die Abfragen gerade; später erneut versuchen.")
    if status >= 400:
        raise ProxmoxLiveError("Der Proxmox-Host meldet einen Fehler.")
    if len(response.content) > _MAX_BODY:
        raise ProxmoxLiveError("Die Antwort des Proxmox-Hosts ist zu groß.")
    try:
        body = response.json()
    except ValueError:
        raise ProxmoxLiveError("Unerwartete Antwort des Proxmox-Hosts.") from None
    if not isinstance(body, dict) or "data" not in body:
        raise ProxmoxLiveError("Unerwartete Antwort des Proxmox-Hosts.")
    return body["data"]


def _data_list(data: object) -> list[dict]:
    if not isinstance(data, list):
        raise ProxmoxLiveError("Unerwartete Antwort des Proxmox-Hosts.")
    return [d for d in data if isinstance(d, dict)]


def _data_dict(data: object) -> dict:
    if not isinstance(data, dict):
        raise ProxmoxLiveError("Unerwartete Antwort des Proxmox-Hosts.")
    return data


def _is_num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pick(entry: dict, fields: tuple[str, ...], secret: str) -> dict:
    """Allowlisted fields with scalar values only (NaN/inf dropped)."""
    picked = {f: entry[f] for f in fields
              if f in entry and (entry[f] is None or isinstance(entry[f], (str, bool))
                                 or (isinstance(entry[f], (int, float)) and _is_num(entry[f])))}
    return redact(picked, secret)  # type: ignore[return-value]


def _bounded(result: dict) -> dict:
    if len(json.dumps(result, ensure_ascii=False)) > MAX_CHARS:
        raise ProxmoxLiveError("Die Antwort des Proxmox-Hosts ist zu groß.")
    return result


def _round(value: float) -> float:
    return round(value, 4) if abs(value) < 100 else round(value)


def _summarize_rrd(data: object, metrics: tuple[str, ...]) -> dict | None:
    """Average and maximum per metric plus at most MAX_POINTS evenly spaced samples; null/NaN
    samples are left out. None when there is no usable sample."""
    rows = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    stats: dict[str, dict] = {}
    for metric in metrics:
        values = [r[metric] for r in rows if _is_num(r.get(metric))]
        if values:
            stats[metric] = {"avg": _round(sum(values) / len(values)), "max": _round(max(values))}
    if not stats:
        return None
    step = max(1, math.ceil(len(rows) / MAX_POINTS))
    points = []
    for row in rows[::step][:MAX_POINTS]:
        point = {m: _round(row[m]) for m in metrics if _is_num(row.get(m))}
        if _is_num(row.get("time")):
            point["time"] = int(row["time"])
        points.append(point)
    return {"messpunkte": len(rows), "kennzahlen": stats, "stuetzpunkte": points}


def _tasks(data: object, secret: str) -> list[dict]:
    """Header data only: no UPID, no log lines. Running tasks have no endtime."""
    rows = _data_list(data)
    rows.sort(key=lambda t: t.get("starttime") if _is_num(t.get("starttime")) else 0, reverse=True)
    return [_pick(t, TASK_FIELDS, secret) for t in rows[:MAX_TASKS]]


def _node_names(data: object) -> list[str]:
    return [n["node"] for n in _data_list(data) if isinstance(n.get("node"), str) and _NODE.match(n["node"])]


async def _resolve_guest(base_url: str, token_id: str, secret: str, ref: str) -> tuple[list[dict], list[str]]:
    """Finds guests by VMID or (case-insensitive) name over all nodes; (matches, problems)."""
    by_vmid = bool(_VMID.fullmatch(ref))
    needle = ref.strip().lower()
    nodes = _node_names(await _request("nodes", base_url, token_id, secret))
    found: list[dict] = []
    problems: list[str] = []
    for node in nodes:
        for kind in _KINDS:
            try:
                guests = _data_list(await _request("guest_list", base_url, token_id, secret, node=node, kind=kind))
            except ProxmoxLiveError as exc:
                problems.append(f"{node}/{kind}: {exc}")
                continue
            for guest in guests:
                if guest.get("template") in (1, "1", True) or not _is_num(guest.get("vmid")):
                    continue
                if (by_vmid and int(guest["vmid"]) == int(ref)) or (
                        not by_vmid and str(guest.get("name") or "").strip().lower() == needle):
                    found.append({"node": node, "typ": kind, "vmid": int(guest["vmid"]),
                                  "name": _clean_text(str(guest.get("name") or ""), secret)})
    return found, problems


async def guest_status(base_url: str, token_id: str, secret: str, *, ref: object, timeframe: object = "hour") -> dict:
    """Status, live load, a short history and the latest task headers of one VM/container."""
    frame = valid_timeframe(timeframe)
    if not isinstance(ref, str) or not ref.strip():
        raise ProxmoxLiveError("Parameter 'guest' fehlt (VMID oder Name als Text).")
    ref = ref.strip()
    found, problems = await _resolve_guest(base_url, token_id, secret, ref)
    note = ("Teilergebnis, nicht alle Nodes/Typen abrufbar: " + "; ".join(problems)) if problems else ""
    if not found:
        result: dict = {"gefunden": False,
                        "hinweis": ("Kein Gast mit dieser VMID/diesem Namen (Templates werden übersprungen)."
                                    + (" " + note if note else ""))}
        return _bounded(result)
    if len(found) > 1:
        return _bounded({"gefunden": None, "mehrdeutig": True, "kandidaten": found[:MAX_ENTRIES],
                         "hinweis": "Mehrere Gäste passen; bitte die VMID angeben." + (" " + note if note else "")})
    target = found[0]
    where = dict(node=target["node"], kind=target["typ"], vmid=target["vmid"])
    current = _data_dict(await _request("guest_status", base_url, token_id, secret, **where))
    status = _pick(current, GUEST_FIELDS, secret)
    ha = current.get("ha")
    if isinstance(ha, dict):
        status["ha"] = _pick(ha, ("managed", "state"), secret)
    result = {"gefunden": True, "node": target["node"], "typ": target["typ"], "status": status}
    hints = [note] if note else []
    try:
        rrd = _summarize_rrd(await _request("guest_rrd", base_url, token_id, secret, timeframe=frame, **where),
                             GUEST_RRD)
        result["verlauf"] = {"zeitraum": frame, **rrd} if rrd else None
        if rrd is None:
            hints.append("Der Proxmox-Host lieferte keinen Verlauf (Gast evtl. gerade erst gestartet).")
    except ProxmoxLiveError as exc:
        result["verlauf"] = None
        hints.append(f"Verlauf nicht abrufbar ({exc})")
    try:
        result["aufgaben"] = _tasks(await _request("node_tasks", base_url, token_id, secret, node=target["node"],
                                                   limit=MAX_TASKS, for_vmid=target["vmid"]), secret)
    except ProxmoxLiveError as exc:
        result["aufgaben"] = []
        hints.append(f"Aufgaben nicht abrufbar ({exc})")
    if hints:
        result["hinweis"] = " ".join(hints)
    return _bounded(result)


async def node_status(base_url: str, token_id: str, secret: str, *, node: object = None,
                      timeframe: object = "hour") -> dict:
    """Load, memory, root filesystem, history and latest task headers of one Proxmox node."""
    frame = valid_timeframe(timeframe)
    names = _node_names(await _request("nodes", base_url, token_id, secret))
    if node in (None, ""):
        if len(names) != 1:
            raise ProxmoxLiveError("Mehrere oder keine Nodes vorhanden, bitte 'node' angeben: "
                                   + (", ".join(names) or "keiner"))
        node = names[0]
    if not isinstance(node, str) or node not in names:
        raise ProxmoxLiveError("Unbekannter Node. Vorhanden: " + (", ".join(names) or "keiner"))
    current = _data_dict(await _request("node_status", base_url, token_id, secret, node=node))
    status = _pick(current, NODE_FIELDS, secret)
    load = current.get("loadavg")
    if isinstance(load, list):
        status["loadavg"] = [str(v)[:12] for v in load[:3] if isinstance(v, (str, int, float))]
    for key in ("memory", "rootfs"):
        if isinstance(current.get(key), dict):
            status[key] = _pick(current[key], ("used", "total", "free"), secret)
    result: dict = {"node": node, "status": status}
    hints = []
    try:
        rrd = _summarize_rrd(await _request("node_rrd", base_url, token_id, secret, node=node, timeframe=frame),
                             NODE_RRD)
        result["verlauf"] = {"zeitraum": frame, **rrd} if rrd else None
    except ProxmoxLiveError as exc:
        result["verlauf"] = None
        hints.append(f"Verlauf nicht abrufbar ({exc})")
    try:
        result["aufgaben"] = _tasks(await _request("node_tasks", base_url, token_id, secret, node=node,
                                                   limit=MAX_TASKS), secret)
    except ProxmoxLiveError as exc:
        result["aufgaben"] = []
        hints.append(f"Aufgaben nicht abrufbar ({exc})")
    if hints:
        result["hinweis"] = " ".join(hints)
    return _bounded(result)
