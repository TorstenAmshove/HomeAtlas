"""Shared target checks for server-side requests to addresses a user or a model supplied (SSRF).

Two policies live here because the callers need different ones:

- `ensure_allowed_target(host, allow_lan=True)`: diagnostics (`http_check`, `check_port`) may reach
  LAN devices (router web UI), so only loopback/link-local/unspecified/multicast/reserved are
  refused. `allow_lan=False` (vendor-doc link check) additionally refuses private networks, since
  vendor documentation is always on the public internet.
- `check_llm_base_url(url)`: the LLM server address is admin-entered and Ollama on localhost or the
  LAN is the normal case, so loopback and LAN stay allowed; only http/https and no link-local
  (cloud metadata), multicast, unspecified or reserved literal addresses. Hostnames are not
  resolved here (the path is synchronous); a name pointing at link-local is a documented residual risk.

DNS rebinding (resolve here, httpx resolves again later) is a known residual risk, as for http_check.
Imports nothing from the rest of the app.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class BlockedTarget(ValueError):
    """The target is, or resolves to, an address that must not be requested."""


def _parse(address: str):
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def is_forbidden_address(address: str, *, allow_lan: bool = True) -> bool:
    try:
        ip = _parse(address)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return True
    if not allow_lan and (ip.is_private or (ip.version == 4 and ip in _CGNAT)):
        return True
    return False


async def ensure_allowed_target(host: str, *, allow_lan: bool = True,
                                forbidden: Callable[[str], bool] | None = None) -> None:
    """Raises BlockedTarget if `host` is, or resolves to, a forbidden address. Every resolved address
    must be allowed. Unresolvable hosts pass (the request itself then fails)."""
    check = forbidden or (lambda a: is_forbidden_address(a, allow_lan=allow_lan))
    host = host.strip("[]")
    try:
        addresses = [str(ipaddress.ip_address(host.split("%", 1)[0]))]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP), timeout=6.0)
        except (socket.gaierror, asyncio.TimeoutError, OSError):
            return
        addresses = [info[4][0] for info in infos]
    if any(check(a) for a in addresses):
        raise BlockedTarget(host)


def _parse_llm_host(host: str):
    """The host as an IP address, or None for a real name. Besides the standard notations this also
    reads the numeric IPv4 forms the system resolver accepts (`2852039166`, `0xa9fea9fe`,
    `169.254.43518`, a trailing dot) -- otherwise they would pass as "names" and reach link-local."""
    try:
        return _parse(host)
    except ValueError:
        pass
    candidate = host.rstrip(".")
    if not candidate or not all(c in "0123456789abcdefxABCDEFX." for c in candidate):
        return None
    try:
        return ipaddress.IPv4Address(socket.inet_aton(candidate))
    except OSError:
        return None


def check_llm_base_url(url: str) -> None:
    """Raises BlockedTarget with a user-facing German message if the LLM server address is unusable."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - validates the port
    except ValueError:
        raise BlockedTarget("Die Server-Adresse ist ungültig.") from None
    if parts.scheme not in ("http", "https"):
        raise BlockedTarget("Die Server-Adresse muss mit http:// oder https:// beginnen.")
    if not host:
        raise BlockedTarget("Die Server-Adresse enthält keinen Host.")
    if parts.username is not None or parts.password is not None:
        raise BlockedTarget("Die Server-Adresse darf keine Zugangsdaten enthalten.")
    ip = _parse_llm_host(host)
    if ip is None:
        return  # a name: not resolved here
    if ip.is_loopback:
        return  # ::1 counts as "reserved" in the stdlib, so check loopback first
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        raise BlockedTarget("Link-Local-, Multicast- und unspezifizierte Adressen sind als Server-Adresse nicht erlaubt.")
