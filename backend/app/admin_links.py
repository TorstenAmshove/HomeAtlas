"""Deep links from a device page into the tools that actually manage it (Portainer, Proxmox UI).

Pure link computation, no I/O and no device access: HomeAtlas only points the admin to the right
place, it does not control anything there. Only the `url` fields of accounts/systems are ever
passed in, never a secret. The route serving this is admin-only; members never load the links."""
from __future__ import annotations

from urllib.parse import quote, urlsplit


def normalize_web_url(value: str) -> str:
    """Validated base URL without trailing slash; "" stays "". Raises ValueError on anything that is
    not a plain http(s) URL (no userinfo, query, fragment or whitespace)."""
    value = (value or "").strip()
    if not value:
        return ""
    if any(c.isspace() for c in value):
        raise ValueError("URL darf keine Leerzeichen enthalten.")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Bitte eine URL mit http:// oder https:// angeben.")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment \
            or "?" in value or "#" in value:
        raise ValueError("URL darf keine Zugangsdaten, Query oder Fragment enthalten.")
    return f"{parts.scheme.lower()}://{parts.netloc}{parts.path.rstrip('/')}"


def _origin(url: str | None) -> str:
    """scheme://host[:port] of a stored URL (an account URL is an API address and may carry a path)."""
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username is not None:
        return ""
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme.lower()}://{host}{f':{port}' if port else ''}"


def _proxmox_base(settings: dict, parent: dict | None, parent_account_urls: list[str]) -> str:
    try:
        configured = normalize_web_url(settings.get("proxmoxWebUrl") or "")
    except ValueError:
        configured = ""
    if configured:
        return configured
    for url in parent_account_urls:
        if url and url.strip():
            return _origin(url)
    return _origin((parent or {}).get("url"))


def build(system: dict, settings: dict, parent: dict | None, parent_account_urls: list[str]) -> list[dict]:
    extra = system.get("extra") if isinstance(system.get("extra"), dict) else {}
    docker = extra.get("docker") if isinstance(extra.get("docker"), dict) else {}
    proxmox = extra.get("proxmox") if isinstance(extra.get("proxmox"), dict) else {}
    links: list[dict] = []

    container_id = str(docker.get("containerId") or "")
    base, env = (settings.get("portainerUrl") or "").strip(), str(settings.get("portainerEnvId") or "").strip()
    if system.get("kind") == "container" and container_id and base and env:
        links.append({"label": "In Portainer öffnen",
                      "url": f"{base}/#!/{quote(env, safe='')}/docker/containers/{quote(container_id, safe='')}"})

    vmid = str(proxmox.get("vmid") or "").strip()
    if proxmox.get("node") and vmid.isascii() and vmid.isdigit() and not docker:
        # The scan's guest type wins over the device kind (a guest may be kind "smarthome"); the
        # kind mapping is only the fallback for rows stored before `type` existed.
        guest_type = proxmox.get("type")
        if not (isinstance(guest_type, str) and guest_type in ("qemu", "lxc")):
            guest_type = {"vm": "qemu", "container": "lxc"}.get(system.get("kind"))
        base = _proxmox_base(settings, parent, parent_account_urls) if guest_type else ""
        if base:
            links.append({"label": "In Proxmox öffnen", "url": f"{base}/#v1:0:={guest_type}%2F{vmid}"})
    return links
