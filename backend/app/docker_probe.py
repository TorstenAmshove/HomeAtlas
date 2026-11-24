"""Reads the Docker host through a read-only socket proxy (see docker-compose.yml, ADR-0024).

This is the single highest-value discovery source in a self-hosted household: a port scan can only
say "something answers on 8180", while the Docker API says which image it is, which compose
project it belongs to, which volumes hold its data and whether it is set to restart on boot --
exactly the facts someone needs six months later when it breaks.

Read-only in the honest sense: only GET endpoints are ever called, and only these paths: /version,
/info, /containers/json, /networks, /volumes. Never the per-container inspect endpoint (it returns
`Config.Env` in clear text, and a proxy cannot filter content), so the shipped proxy can deny it
completely. The endpoint comes from `DOCKER_HOST` (unix:// or loopback tcp://), then `DOCKER_SOCKET`
(installations that still mount the raw socket), then the default socket path.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import httpx

_DEFAULT_SOCKET = "/var/run/docker.sock"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


# DynDNS clients are recognised by image name only. Their hostnames are NOT read from the container
# environment (that would need the inspect endpoint, ADR-0024) but from an operator-set label on the
# container, which `/containers/json` already returns:
#   homeatlas.ddns.hosts=home.example.net,vpn.example.net   (comma/space separated)
#   homeatlas.ddns.ipv6=true|false                           (default: true for Cloudflare, else false)
_DDNS_IMAGES = {
    "favonia/cloudflare-ddns": "Cloudflare", "cloudflare-ddns": "Cloudflare", "ddclient": "ddclient",
    "ddns-updater": "ddns-updater", "inadyn": "inadyn", "ddnss": "DDNSS",
}
_DDNS_LABEL_HOSTS = "homeatlas.ddns.hosts"
_DDNS_LABEL_IPV6 = "homeatlas.ddns.ipv6"
_HOSTNAME = re.compile(r"^([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")


def _ddns_provider(image: str) -> str:
    low = (image or "").lower()
    return next((label for key, label in _DDNS_IMAGES.items() if key in low), "")


def ddns_fact(image: str, labels: dict | None, via: str) -> dict | None:
    """Builds a `ddns` fact from an image name and the container labels (no environment involved)."""
    provider = _ddns_provider(image)
    if not provider:
        return None
    labels = labels if isinstance(labels, dict) else {}
    hosts: list[str] = []
    for part in re.split(r"[,\s]+", str(labels.get(_DDNS_LABEL_HOSTS) or "")[:2000]):
        part = part.strip().lower().rstrip(".")
        if part and len(part) <= 253 and _HOSTNAME.match(part) and part not in hosts:
            hosts.append(part)
    flag = str(labels.get(_DDNS_LABEL_IPV6) or "").strip().lower()
    ipv6 = flag == "true" if flag in ("true", "false") else provider == "Cloudflare"
    name = image.rsplit("/", 1)[-1].split(":", 1)[0][:100]
    return {"kind": "ddns", "key": name, "data": {
        "client": name, "provider": provider, "hosts": hosts[:20], "ipv4": True, "ipv6": ipv6, "via": via}}


# Socket proxies are recognised by image name; a renamed or mirrored proxy image is deliberately
# still reported (a false warning is the safe direction).
_PROXY_IMAGES = ("wollomatic/socket-proxy", "tecnativa/docker-socket-proxy", "linuxserver/socket-proxy")


def _is_socket_path(path: str) -> bool:
    return str(path or "").rstrip("/").endswith("docker.sock")


def has_docker_socket(container: dict) -> bool:
    """True when the container bind-mounts a Docker socket (also `:ro`, which does not limit the API)."""
    for m in container.get("Mounts") or []:
        if isinstance(m, dict) and m.get("Type", "bind") == "bind" \
                and (_is_socket_path(m.get("Source")) or _is_socket_path(m.get("Destination"))):
            return True
    return False


def is_socket_proxy(image: str) -> bool:
    low = (image or "").lower()
    return any(p in low for p in _PROXY_IMAGES)


def _endpoint() -> tuple[str, str]:
    """Returns ("unix", path) or ("tcp", base_url); ("", reason) when nothing usable is configured.

    Read from the environment on every call. tcp:// is accepted for loopback only: the proxy must
    never be reachable from the LAN, and a remote host would also send the inventory over plain HTTP.
    """
    host = os.environ.get("DOCKER_HOST", "").strip()
    if host:
        parts = urlsplit(host)
        if parts.scheme == "unix" and parts.path:
            return "unix", parts.path
        if parts.scheme == "tcp" and parts.hostname in ("127.0.0.1", "localhost", "::1") and parts.port:
            netloc = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
            return "tcp", f"http://{netloc}:{parts.port}"
        return "", "DOCKER_HOST muss unix://… oder tcp://127.0.0.1:<Port> sein"
    return "unix", os.environ.get("DOCKER_SOCKET", "").strip() or _DEFAULT_SOCKET


def socket_available() -> bool:
    """A unix endpoint needs its socket file; for tcp only a failing request can tell (-> "nicht erreichbar")."""
    kind, value = _endpoint()
    if kind == "unix":
        return os.path.exists(value)
    return kind == "tcp"


_NOT_SET_UP = "Docker-Zugriff nicht eingerichtet (DOCKER_HOST bzw. Socket-Proxy fehlt)"


async def _get(path: str) -> object:
    kind, value = _endpoint()
    if kind == "unix":
        client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=value), base_url="http://docker", timeout=_TIMEOUT)
    elif kind == "tcp":
        client = httpx.AsyncClient(base_url=value, timeout=_TIMEOUT)
    else:
        raise ValueError(value)
    async with client:
        resp = await client.get(path)
    resp.raise_for_status()
    return resp.json()


def _clean_name(names: list[str] | None) -> str:
    if not names:
        return "unbenannter Container"
    return names[0].lstrip("/")


def _published_ports(container: dict) -> list[int]:
    """Only ports actually published to the host -- an internal container port says nothing about
    what is reachable from the network, and listing it would make the documentation misleading."""
    ports = {p["PublicPort"] for p in container.get("Ports") or [] if p.get("PublicPort")}
    return sorted(ports)


def _restart_policy(container: dict, labels: dict) -> str:
    """The real policy lives in HostConfig, not in a "restart" label; the label is only a fallback
    for tools that mirror it there."""
    policy = ((container.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or ""
    return policy if policy and policy != "no" else (labels.get("restart", "") or policy)


def _port_mappings(container: dict) -> list[str]:
    out = []
    for p in container.get("Ports") or []:
        if p.get("PublicPort"):
            out.append(f"{p.get('IP') or '0.0.0.0'}:{p['PublicPort']} -> {p.get('PrivatePort')}/{p.get('Type', 'tcp')}")
    return sorted(set(out))


async def probe(host_ip: str = "") -> dict:
    """Returns {"ok", "error", "version", "systems": [...], "networks": [...], "volumes": [...]}.

    `systems` entries are ready for `db.upsert_discovered_system`.
    """
    if not socket_available():
        return {"ok": False, "error": f"{_NOT_SET_UP}.", "systems": []}
    try:
        version = await _get("/version")
        info = await _get("/info")
        containers = await _get("/containers/json?all=1")
        networks = await _get("/networks")
        volumes = await _get("/volumes")
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"Docker-API nicht erreichbar: {exc}", "systems": []}

    assert isinstance(containers, list)
    volume_list = (volumes or {}).get("Volumes") or [] if isinstance(volumes, dict) else []
    # "Where is this container?" has exactly one useful answer for a household: the machine it
    # runs on. Docker's /info reports that host's own name, which beats a room label nobody would
    # ever fill in for 30 containers.
    host_name = (info or {}).get("Name", "") if isinstance(info, dict) else ""
    location = host_name or host_ip or "Docker-Host"

    ddns: list[dict] = []
    for container in containers:
        if container.get("State") != "running" or not _ddns_provider(container.get("Image", "")):
            continue
        fact = ddns_fact(container.get("Image", ""), container.get("Labels"), host_ip)
        if fact:
            ddns.append(fact)

    systems = []
    for container in containers:
        labels = container.get("Labels") or {}
        project = labels.get("com.docker.compose.project", "")
        service = labels.get("com.docker.compose.service", "")
        container_name = _clean_name(container.get("Names"))
        # Several compose projects commonly run a service with the same name (a postgres per
        # stack); "<service> · <project>" keeps them apart and readable. Without both labels the
        # plain Docker container name is the best identifier there is.
        name = f"{service} · {project}" if project and service else container_name
        mounts = [
            m.get("Name") or m.get("Source") or ""
            for m in container.get("Mounts") or []
            if m.get("Name") or m.get("Source")
        ]
        state = container.get("State", "")
        published = _published_ports(container)
        # The container's own ID changes on every recreate (a rebuild, `docker compose up
        # --build`, even a plain restart-with-new-image) -- keying on it here made every redeploy
        # of a compose-managed container add a brand-new "duplicate" row instead of updating the
        # existing one. Compose project+service survives a recreate; a container's own --name
        # (used for the handful of non-compose containers) is just as stable. Only a bare `docker
        # run` container with no name at all falls back to its ID, and even that keeps the ID
        # constant across rescans since nothing there recreates it.
        stable_key = f"{project}:{service}" if project and service else container_name or container.get("Id", "")[:12]
        # Before compose project+service became the key, every container was keyed on its own ID
        # (see the note above) -- an installation upgrading across that change would otherwise fail
        # to find its existing row by the new key and duplicate every compose-managed container.
        # This lets db.upsert_discovered_system fall back to the old key and migrate the row in place.
        legacy_key = f"docker:{container.get('Id', '')[:12]}"
        systems.append({
            "discoveryKey": f"docker:{stable_key}",
            "legacyDiscoveryKeys": [legacy_key],
            "kind": "container",
            "name": name,
            "ip": host_ip,
            "location": location,
            "model": container.get("Image", ""),
            "status": "online" if state == "running" else "offline",
            "discovered": 1,
            "discoverySource": "docker",
            "openPorts": published,
            "url": f"http://{host_ip}:{published[0]}" if host_ip and published else "",
            "extra": {
                "docker": {
                    # Full ID, unlike discoveryKey's [:12]: the exact ID is right here, so there is
                    # no reason to rely on short-ID resolution later.
                    "containerId": container.get("Id", ""),
                    "image": container.get("Image", ""),
                    "imageId": (container.get("ImageID") or "")[:19],
                    "state": state,
                    "status": container.get("Status", ""),
                    "composeProject": project,
                    "composeService": service,
                    "restartPolicy": _restart_policy(container, labels),
                    "portMappings": _port_mappings(container),
                    "volumes": mounts,
                    "networks": sorted((container.get("NetworkSettings") or {}).get("Networks", {}).keys()),
                    # Reverse proxies on the same Docker network target these addresses, not the host.
                    "networkIps": sorted({n.get("IPAddress") for n in
                                          ((container.get("NetworkSettings") or {}).get("Networks") or {}).values()
                                          if isinstance(n, dict) and n.get("IPAddress")}),
                    "created": container.get("Created"),
                    # Full Docker access (= root on the host); a socket proxy image is not flagged.
                    "dockerSocket": has_docker_socket(container) and not is_socket_proxy(container.get("Image", "")),
                }
            },
        })

    return {
        "ok": True,
        "error": "",
        "hostName": host_name,
        "version": {
            "version": (version or {}).get("Version", "") if isinstance(version, dict) else "",
            "apiVersion": (version or {}).get("ApiVersion", "") if isinstance(version, dict) else "",
            "os": (version or {}).get("Os", "") if isinstance(version, dict) else "",
            "arch": (version or {}).get("Arch", "") if isinstance(version, dict) else "",
        },
        "systems": systems,
        "ddns": ddns,
        "networks": [
            {
                "name": n.get("Name", ""),
                "driver": n.get("Driver", ""),
                "subnet": ", ".join(
                    c.get("Subnet", "") for c in ((n.get("IPAM") or {}).get("Config") or []) if c.get("Subnet")
                ),
            }
            for n in (networks if isinstance(networks, list) else [])
        ],
        "volumes": [
            {"name": v.get("Name", ""), "mountpoint": v.get("Mountpoint", ""), "driver": v.get("Driver", "")}
            for v in volume_list
        ],
    }


# --- Live status for the assistant (ADR-0022) -------------------------------------------------
# `live_containers` is the only thing the assistant's `get_container_status` tool reaches here. It
# issues exactly one request, `GET /containers/json?all=1`, never the per-container inspect endpoint:
# inspect returns `Config.Env` in clear text (possible secrets), and a socket proxy cannot filter
# that out. Without inspect no environment value ever reaches HomeAtlas on this path, and a proxy can
# deny `/containers/{id}/json` completely. Output is built from a field allowlist; Command, Env,
# Mounts, Ports and all labels except the compose project/service are never copied.
_LIVE_LIST_PATH = "/containers/json?all=1"

_EXIT_MEANING = {
    0: "regulär beendet",
    1: "Fehler in der Anwendung",
    125: "Container konnte nicht gestartet werden",
    126: "Startbefehl nicht ausführbar",
    127: "Startbefehl nicht gefunden",
    137: "vom System beendet, oft Speicher voll (SIGKILL)",
    139: "Absturz (SIGSEGV)",
    143: "sauber gestoppt (SIGTERM)",
}
_RE_EXITED = re.compile(r"^(?:Exited|Restarting) \((-?\d+)\)")
_RE_PARENS = re.compile(r"\s*\([^)]*\)")
_IMAGE_USERINFO = re.compile(r"^[^/@\s]*@(?=[^@]*/)")


def exit_meaning(code: int | None) -> str | None:
    if code is None:
        return None
    return _EXIT_MEANING.get(code, "unbekannter Exit-Code")


def _parse_status(status: str) -> dict:
    """Derives exit code, health and the age text from Docker's human `Status` string."""
    status = str(status or "").strip()[:200]
    m = _RE_EXITED.match(status)
    code = int(m.group(1)) if m else None
    low = status.lower()
    if "(unhealthy)" in low:
        health = "unhealthy"
    elif "(healthy)" in low:
        health = "healthy"
    elif "(health: starting)" in low:
        health = "starting"
    else:
        health = None
    return {"exitCode": code, "exitMeaning": exit_meaning(code), "health": health,
            "since": _RE_PARENS.sub("", status).strip()}


def _live_row(container: dict) -> dict:
    labels = container.get("Labels") if isinstance(container.get("Labels"), dict) else {}
    names = container.get("Names")
    row = {
        "name": _clean_name(names if isinstance(names, list) else None)[:100],
        "image": _IMAGE_USERINFO.sub("", str(container.get("Image") or ""))[:200],
        "state": str(container.get("State") or "")[:20],
        "status": str(container.get("Status") or "")[:200],
    }
    row.update(_parse_status(container.get("Status")))
    row["composeProject"] = str(labels.get("com.docker.compose.project") or "")[:100]
    row["_service"] = str(labels.get("com.docker.compose.service") or "")[:100]
    row["_id"] = str(container.get("Id") or "")[:64]
    return row


async def live_containers() -> dict:
    """Returns {"ok", "error", "containers": [...]} from the local Docker API, never raises.

    Rows carry the internal keys `_service` and `_id`, which `tools.py` uses for matching and drops.
    """
    if not socket_available():
        return {"ok": False, "error": f"{_NOT_SET_UP} – Live-Status nicht verfügbar", "containers": []}
    try:
        data = await _get(_LIVE_LIST_PATH)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return {"ok": False, "error": f"Docker-API nicht erreichbar: {exc}"[:300], "containers": []}
    if not isinstance(data, list):
        return {"ok": False, "error": "Docker lieferte keine Containerliste", "containers": []}
    return {"ok": True, "error": "", "containers": [_live_row(c) for c in data if isinstance(c, dict)]}
