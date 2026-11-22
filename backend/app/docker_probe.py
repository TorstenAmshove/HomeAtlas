"""Reads the Docker host through its socket (mounted read-only, see docker-compose.yml).

This is the single highest-value discovery source in a self-hosted household: a port scan can only
say "something answers on 8180", while the Docker API says which image it is, which compose
project it belongs to, which volumes hold its data and whether it is set to restart on boot --
exactly the facts someone needs six months later when it breaks.

Read-only in the honest sense: only GET endpoints are ever called. The socket mount itself is
root-equivalent on the host, which the README states outright.
"""
from __future__ import annotations

import os
import re

import httpx

_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


# DynDNS clients are recognised by image name only; the environment is read (one GET per match) and
# reduced to this allowlist of non-secret keys. Tokens/passwords (CF_API_TOKEN, PASSWORD, CONFIG, ...)
# are never copied, and values are validated as hostnames before they are kept.
_DDNS_IMAGES = {
    "favonia/cloudflare-ddns": "Cloudflare", "cloudflare-ddns": "Cloudflare", "ddclient": "ddclient",
    "ddns-updater": "ddns-updater", "inadyn": "inadyn", "ddnss": "DDNSS",
}
_DDNS_HOST_KEYS = ("DOMAINS", "DOMAIN", "DOMAIN_DDNSS", "HOSTNAME", "HOSTS")
_HOSTNAME = re.compile(r"^([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")


def _ddns_provider(image: str) -> str:
    low = (image or "").lower()
    return next((label for key, label in _DDNS_IMAGES.items() if key in low), "")


def ddns_fact(image: str, env: list[str], via: str) -> dict | None:
    """Builds a `ddns` fact from an image name and its env list, keeping allowlisted keys only."""
    provider = _ddns_provider(image)
    if not provider:
        return None
    values = {k: v for k, _, v in (e.partition("=") for e in env or []) if k in (*_DDNS_HOST_KEYS, "IP4_PROVIDER", "IP6_PROVIDER")}
    hosts: list[str] = []
    for key in _DDNS_HOST_KEYS:
        for part in re.split(r"[,\s]+", values.get(key, "")):
            part = part.strip().lower().rstrip(".")
            if part and len(part) <= 253 and _HOSTNAME.match(part) and part not in hosts:
                hosts.append(part)
    cloudflare = provider == "Cloudflare"
    ipv4 = values.get("IP4_PROVIDER", "").lower() != "none"
    ipv6 = values.get("IP6_PROVIDER", "").lower() != "none" if cloudflare and "IP6_PROVIDER" not in values \
        else values.get("IP6_PROVIDER", "none").lower() != "none"
    name = image.rsplit("/", 1)[-1].split(":", 1)[0][:100]
    return {"kind": "ddns", "key": name, "data": {
        "client": name, "provider": provider, "hosts": hosts[:20], "ipv4": ipv4, "ipv6": ipv6, "via": via}}


def socket_available() -> bool:
    return os.path.exists(_SOCKET)


async def _get(path: str) -> object:
    transport = httpx.AsyncHTTPTransport(uds=_SOCKET)
    async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=_TIMEOUT) as client:
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
        return {"ok": False, "error": f"Docker-Socket {_SOCKET} ist nicht eingebunden.", "systems": []}
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
        cid = str(container.get("Id", ""))
        try:
            env = ((await _get(f"/containers/{cid}/json")).get("Config") or {}).get("Env") or [] if re.match(r"^[0-9a-f]{12,64}$", cid) else []
        except (httpx.HTTPError, ValueError, AttributeError):
            env = []
        fact = ddns_fact(container.get("Image", ""), env, host_ip)
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
                    # Full ID, unlike discoveryKey's [:12] -- docker_admin.py's start/stop/restart/
                    # exec actions need the exact ID, and Docker's actions API accepts short IDs
                    # too but there is no reason to rely on that when the full one is right here.
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
