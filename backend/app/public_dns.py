"""Public DNS resolution of the public hostnames found by the other sources.

Why not the system resolver: with split DNS (AdGuard rewrites, router) it would answer with the
*internal* address and make every host look "not on the WAN IP". So this module asks a fixed public
resolver over DNS-over-HTTPS (GET), the only contact besides Cloudflare outside the LAN (ADR-0014).
Opt-in (`scanEnablePublicDns`, default off). It reveals the household's hostnames to that resolver;
the README says so.

Only validated hostnames from stored facts are queried, never wildcards, at most `MAX_QUERIES` per
scan (A and AAAA count separately); the rest is reported as skipped. Answers are size-capped and
only IP addresses and the first CNAME are kept.
"""
from __future__ import annotations

import ipaddress

import httpx

from .cloudflare_probe import clean_host

RESOLVER = "https://cloudflare-dns.com/dns-query"
MAX_QUERIES = 200
_MAX_BODY = 65536
_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_TYPES = (("A", 1), ("AAAA", 28))


def hostnames(facts: list[dict]) -> list[str]:
    """Public hostnames (no wildcards, no internal Traefik routes) worth resolving."""
    found: list[str] = []
    for f in facts:
        d = f.get("data") or {}
        if f.get("kind") in ("caddy_site", "tunnel_ingress", "cf_dns"):
            names = [d.get("host")]
        elif f.get("kind") == "ddns":
            names = d.get("hosts") or []
        else:
            continue
        for n in names:
            host = clean_host(n)
            if host and "*" not in host and host not in found:
                found.append(host)
    return sorted(found)


async def _ask(client: httpx.AsyncClient, host: str, qtype: str, code: int) -> tuple[list[str], str]:
    response = await client.get(RESOLVER, params={"name": host, "type": qtype},
                                headers={"accept": "application/dns-json"})
    response.raise_for_status()
    if len(response.content) > _MAX_BODY:
        raise ValueError("Antwort zu groß")
    data = response.json()
    addrs: list[str] = []
    cname = ""
    for answer in (data.get("Answer") or [])[:20] if isinstance(data, dict) else []:
        value = str(answer.get("data") or "")
        if answer.get("type") == code:
            try:
                addrs.append(str(ipaddress.ip_address(value)))
            except ValueError:
                continue
        elif answer.get("type") == 5 and not cname:
            cname = clean_host(value)
    return addrs, cname


async def resolve(hosts: list[str]) -> dict:
    """Returns {"ok", "error", "facts", "skipped"}; `ok` is False only if nothing could be resolved."""
    hosts = [h for h in (clean_host(h) for h in hosts) if h and "*" not in h]
    budget = MAX_QUERIES // len(_TYPES)
    todo, skipped = hosts[:budget], max(0, len(hosts) - budget)
    facts: list[dict] = []
    failures = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for host in todo:
                addrs: list[str] = []
                cname = ""
                try:
                    for qtype, code in _TYPES:
                        a, c = await _ask(client, host, qtype, code)
                        addrs += a
                        cname = cname or c
                except (httpx.HTTPError, ValueError):
                    failures += 1
                    continue
                facts.append({"kind": "dns", "key": host, "data": {"host": host, "addrs": addrs[:10], "cname": cname}})
    except httpx.HTTPError as exc:
        return {"ok": False, "facts": [], "skipped": skipped, "error": f"Öffentliches DNS nicht erreichbar ({type(exc).__name__})."}
    if todo and not facts:
        return {"ok": False, "facts": [], "skipped": skipped, "error": "Öffentliches DNS lieferte keine Antwort."}
    return {"ok": True, "error": "", "facts": facts, "skipped": skipped + failures}
