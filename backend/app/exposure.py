"""Builds reachability chains ("who can reach which service, over which path") from stored facts.

Pure function module (ADR-0014): no network, no database, no import of httpx/asyncssh or of any
writing module. The caller (`docs.py`, later `tools.py`) hands in already-stored facts, the
inventory and the WAN address, so this logic is testable without any source being reachable.

Fact shapes (`data` of an `exposureFacts` row; hostnames lower-case, no trailing dot, <= 253):
  caddy_site      {host, upstreams[], mtls, via}        via = IP of the system serving the file
  tunnel_ingress  {host, origin, tls_noverify, via}
  cf_dns          {host, type, target, proxied, provider?}
  cf_waf_mtls     {host}
  cf_tunnel       {id, name, status}                  status "healthy"/"degraded"/"down"/"inactive"
  dns             {host, addrs[], cname?}               public resolution (never the LAN resolver)
  traefik_router  {hosts[], service, resolver, middlewares[], tls}
  ddns            {client, provider, hosts[], ipv4, ipv6, via}
  portforward     {proto, wanPort, destIp, destPort, enabled}
  portforward_scan {count}                      marker: the router was read ("no forwards" vs. unknown)
  wan_address     {ip, source, origin?}                 public address from UniFi or the FRITZ!Box

Path status (per configured path of a public host):
  aktiv    public DNS/Cloudflare leads to this path (tunnel CNAME, or WAN IP plus a port forward)
  verwaist configured, but nothing from outside leads there
  unklar   data is missing (source off/stale, DNS unknown) -- never reported as orphaned
"""
from __future__ import annotations

import ipaddress
import re

MAX_DEPTH = 8
ORPHAN_HINT = "Pfad über {source} ist konfiguriert, aber von außen nicht erreichbar – entfernen oder dokumentieren."
_TUNNEL_SUFFIX = ".cfargotunnel.com"
_SOURCE_LABEL = {"caddy": "DMZ-Proxy (Caddy)", "tunnel": "Tunnel (cloudflared)"}
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def norm_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")[:253]


def _split_target(target: str) -> tuple[str, int | None]:
    """'http://10.0.0.5:8080/x', '10.0.0.5:8080', '[::1]:80', 'unix:/run/x.sock' -> (host, port)."""
    t = (target or "").strip()
    if not t or t.startswith(("unix:", "unix/", "/")):
        return "", None
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t, flags=re.I)
    t = t.split("/", 1)[0].rsplit("@", 1)[-1]
    m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", t)
    if m:
        return m.group(1).lower(), int(m.group(2)) if m.group(2) else None
    if t.count(":") == 1:
        host, _, port = t.partition(":")
        return host.lower(), int(port) if port.isdigit() else None
    return t.lower(), None


def _ip_eq(a: str, b: str) -> bool:
    try:
        return ipaddress.ip_address(a) == ipaddress.ip_address(b)
    except ValueError:
        return False


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _mapped_ports(system: dict) -> set[int]:
    ports: set[int] = set()
    docker = (system.get("extra") or {}).get("docker") or {}
    for mapping in docker.get("portMappings") or []:
        m = re.match(r"^.*:(\d+) ->", str(mapping))
        if m:
            ports.add(int(m.group(1)))
    return ports


def _on_docker_network(system: dict, ip: str) -> bool:
    """True if `ip` is the container's own address on a Docker network (a proxy's usual target)."""
    addresses = ((system.get("extra") or {}).get("docker") or {}).get("networkIps") or []
    return any(_ip_eq(str(a), ip) for a in addresses)


def resolve_target(target: str, systems: list[dict], via: str = "") -> dict:
    """Maps one chain target to inventory systems. Several hits are all returned, never guessed."""
    host, port = _split_target(target)
    result = {"target": f"{host}:{port}" if host and port else host or (target or "")[:80],
              "systems": [], "inInventory": False}
    if not host:
        return result
    if host in _LOOPBACK:
        host = via or host
    if _is_ip(host):
        same_ip = [s for s in systems if s.get("ip") and _ip_eq(s["ip"], host)]
        containers = [s for s in same_ip if port and port in _mapped_ports(s)]
        hits = containers or [s for s in same_ip if s.get("kind") != "container"] or same_ip
        hits = hits or [s for s in systems if _on_docker_network(s, host)]
    else:
        hits = [s for s in systems if norm_host(s.get("name", "")) == host or norm_host(s.get("hostname", "")) == host]
    result["systems"] = [{"id": s["id"], "name": s["name"], "kind": s.get("kind", ""),
                          "status": s.get("status", "unknown")} for s in hits]
    result["inInventory"] = bool(hits)
    return result


def _is_global(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _wan_rank(data: dict) -> int:
    """A public interface address is first-hand, then the FRITZ!Box; UniFi's geo data can be stale."""
    if data.get("source") == "FRITZ!Box":
        return 1
    return 0 if data.get("origin") == "interface" else 2


def _by_kind(facts: list[dict], kind: str) -> list[dict]:
    return [f for f in facts if f.get("kind") == kind]


def build_chains(facts: list[dict], systems: list[dict], wan: dict | None = None) -> dict:
    """`facts` are stored rows (`kind`, `data`, `stale`, `lastSeen`); `wan` is `{ip, type}` or None."""
    row_ip = ((wan or {}).get("ip") or "").strip()
    reported = sorted((f["data"] for f in _by_kind(facts, "wan_address")
                       if not f.get("stale") and _is_global(str(f["data"].get("ip") or ""))), key=_wan_rank)
    public = list(dict.fromkeys(str(d["ip"]) for d in reported))
    wan_ip = public[0] if public else row_ip
    wan_ips = [wan_ip] if wan_ip else []
    hints: list[str] = []
    if len(public) > 1:
        hints.append("UniFi und FRITZ!Box melden unterschiedliche öffentliche Adressen; "
                     f"verwendet wird die von {reported[0].get('source', 'UniFi')}.")
    elif reported and _wan_rank(reported[0]) == 2:
        hints.append("Die öffentliche Adresse stammt aus den Standortdaten von UniFi und kann veraltet sein.")
    stale_sources = sorted({f.get("source", "") for f in facts if f.get("stale")} - {""})
    for source in stale_sources:
        newest = max((f.get("lastSeen", "") for f in facts if f.get("source") == source), default="")
        hints.append(f"Quelle „{source}“ war beim letzten Scan nicht lesbar – Stand von {newest[:16]}.")

    portforwards = [f["data"] for f in _by_kind(facts, "portforward")]
    cf_dns = {norm_host(f["data"].get("host", "")): f["data"] for f in _by_kind(facts, "cf_dns")}
    dns = {norm_host(f["data"].get("host", "")): f["data"] for f in _by_kind(facts, "dns")}
    waf = {norm_host(f["data"].get("host", "")) for f in _by_kind(facts, "cf_waf_mtls")}
    traefik_hosts = {norm_host(h): f["data"] for f in _by_kind(facts, "traefik_router")
                     for h in f["data"].get("hosts") or []}

    paths_by_host: dict[str, list[dict]] = {}
    for f in _by_kind(facts, "caddy_site"):
        d = f["data"]
        paths_by_host.setdefault(norm_host(d.get("host", "")), []).append(
            {"source": "caddy", "targets": list(d.get("upstreams") or []), "via": d.get("via", ""),
             "mtls": bool(d.get("mtls")), "stale": bool(f.get("stale"))})
    for f in _by_kind(facts, "tunnel_ingress"):
        d = f["data"]
        paths_by_host.setdefault(norm_host(d.get("host", "")), []).append(
            {"source": "tunnel", "targets": [d.get("origin", "")], "via": d.get("via", ""),
             "mtls": False, "stale": bool(f.get("stale"))})

    def is_wan(address: str) -> bool:
        return any(_ip_eq(address, w) for w in wan_ips)

    def points_to_wan(host: str) -> bool | None:
        addrs = list((dns.get(host) or {}).get("addrs") or [])
        cf = cf_dns.get(host)
        if cf and cf.get("type") in ("A", "AAAA"):
            addrs.append(cf.get("target", ""))
        if not wan_ip or not (addrs or host in dns or cf):
            return None
        return any(is_wan(a) for a in addrs)

    def has_forward(via: str) -> bool | None:
        if not portforwards:
            return None
        return any(p.get("enabled", True) and via and _ip_eq(str(p.get("destIp", "")), via) for p in portforwards)

    def follow(target: str, via: str, depth: int, seen: set[str]) -> list[dict]:
        """One chain step per hop; a target that is itself a proxied hostname is followed further."""
        step = resolve_target(target, systems, via)
        steps = [{"label": step["target"], **{k: step[k] for k in ("systems", "inInventory")}}]
        host, _ = _split_target(target)
        nxt = traefik_hosts.get(host) or (paths_by_host.get(host, [{}])[0] if host in paths_by_host else None)
        if nxt and host not in seen:
            if depth >= MAX_DEPTH:
                steps.append({"label": "Kette zu tief – abgebrochen", "systems": [], "inInventory": False})
            else:
                for t in (nxt.get("targets") or [nxt.get("service", "")])[:1]:
                    steps += follow(t, via, depth + 1, seen | {host})
        return steps

    chains = []
    for host in sorted(h for h in paths_by_host if h and "*" not in h):
        paths = []
        for path in paths_by_host[host]:
            wan_hit, fwd = points_to_wan(host), has_forward(path["via"])
            cf = cf_dns.get(host)
            if path["stale"]:
                status = "unklar"
            elif path["source"] == "tunnel":
                if cf and str(cf.get("target", "")).endswith(_TUNNEL_SUFFIX):
                    status = "aktiv"
                elif cf or host in dns:
                    status = "verwaist"
                else:
                    status = "unklar"
            else:
                if wan_hit and fwd:
                    status = "aktiv"
                elif wan_hit is None or (wan_hit and fwd is None):
                    status = "unklar"
                else:
                    status = "verwaist"
            steps = []
            for t in path["targets"][:3]:
                hops = follow(t, path["via"], 0, {host})
                hops[0]["fromVia"] = True  # the proxy/tunnel connects to this hop itself
                steps += hops
            paths.append({"source": path["source"], "sourceLabel": _SOURCE_LABEL[path["source"]],
                          "status": status, "mtls": path["mtls"] or host in waf, "via": path["via"], "steps": steps})
        chain = {"host": host, "paths": paths, "cloudflare": bool(cf_dns.get(host, {}).get("proxied")),
                 "mtlsCloudflare": host in waf, "hints": []}
        if len(paths) > 1 or any(p["status"] == "verwaist" for p in paths):
            for p in paths:
                if p["status"] == "verwaist":
                    chain["hints"].append(ORPHAN_HINT.format(source=p["sourceLabel"]))
        for p in paths:
            for step in p["steps"]:
                if step["inInventory"] is False and step["label"] and "tief" not in step["label"]:
                    chain["hints"].append(f"Ziel {step['label']} ist nicht im Inventar.")
                for s in step["systems"]:
                    if s["status"] == "offline":
                        chain["hints"].append(f"Ziel {s['name']} ist nicht erreichbar oder gestoppt.")
        chain["hints"] = list(dict.fromkeys(chain["hints"]))
        chains.append(chain)

    tunnels = {f["data"].get("id", ""): f["data"] for f in _by_kind(facts, "cf_tunnel")}
    for cf in cf_dns.values():
        target = str(cf.get("target", ""))
        tunnel = tunnels.get(target[:-len(_TUNNEL_SUFFIX)]) if target.endswith(_TUNNEL_SUFFIX) else None
        if tunnel and tunnel.get("status") in ("down", "inactive"):
            hints.append(f"Cloudflare-Tunnel „{tunnel.get('name', '')}“ ist nicht verbunden.")

    external = []
    direct_hosts: dict[str, dict] = {}
    for host, cf in sorted(cf_dns.items()):
        if "*" in host or host in paths_by_host or str(cf.get("target", "")).endswith(_TUNNEL_SUFFIX):
            continue
        if not wan_ip:
            continue  # without the WAN address nothing can be told apart from the home network
        if cf.get("type") in ("A", "AAAA"):
            addrs = [cf.get("target", "")]
        else:  # CNAME: only the public resolution says where it really ends up
            addrs = list((dns.get(host) or {}).get("addrs") or [])
            if not addrs:
                continue
        if any(is_wan(a) for a in addrs):
            direct_hosts[host] = {"target": cf.get("target", ""), "cloudflare": bool(cf.get("proxied"))}
        else:
            external.append({"host": host, "target": cf.get("target", ""), "provider": cf.get("provider", "")})
    for host, resolved in sorted(dns.items()):  # DynDNS names usually have no Cloudflare record
        if host and "*" not in host and host not in cf_dns and host not in paths_by_host \
                and any(is_wan(a) for a in resolved.get("addrs") or []):
            direct_hosts[host] = {"target": resolved.get("cname") or "", "cloudflare": False}

    internal = []
    for f in _by_kind(facts, "traefik_router"):
        d = f["data"]
        resolved = resolve_target(d.get("service", ""), systems)
        for host in d.get("hosts") or [""]:
            internal.append({"host": norm_host(host), "target": resolved["target"], "systems": resolved["systems"],
                             "inInventory": resolved["inInventory"], "resolver": d.get("resolver", ""),
                             "tls": bool(d.get("tls")), "middlewares": list(d.get("middlewares") or [])})
    internal.sort(key=lambda r: r["host"])

    ddns = []
    for f in _by_kind(facts, "ddns"):
        d = f["data"]
        hosts = [norm_host(h) for h in d.get("hosts") or []]
        rows = []
        for h in hosts:
            hit = points_to_wan(h)
            rows.append({"host": h, "resolvesToWan": hit})
            if hit is False:
                hints.append(f"DynDNS-Hostname {h} zeigt nicht auf die WAN-IP.")
        via = resolve_target(d.get("via", ""), systems)
        ddns.append({"client": d.get("client", ""), "provider": d.get("provider", ""), "ipv4": bool(d.get("ipv4")),
                     "ipv6": bool(d.get("ipv6")), "system": via["systems"], "hosts": rows})

    forwards = []
    for p in portforwards:
        target = resolve_target(f"{p.get('destIp', '')}:{p.get('destPort', '')}", systems)
        forwards.append({**{k: p.get(k) for k in ("proto", "wanPort", "destIp", "destPort", "enabled")},
                         "systems": target["systems"]})
        if not target["inInventory"]:
            hints.append(f"Portweiterleitung auf {p.get('destIp', '')} hat kein Ziel im Inventar.")

    forwards_read = any(not f.get("stale") for f in _by_kind(facts, "portforward_scan"))
    open_forwards = [p for p in forwards if p.get("enabled", True)]
    direct = [{"host": host, **row, "mtls": host in waf,
               "status": "aktiv" if open_forwards else "verwaist" if forwards_read else "unklar",
               "forwards": open_forwards} for host, row in sorted(direct_hosts.items())]
    if direct and open_forwards and not _by_kind(facts, "caddy_site"):
        hints.append("Welcher Dienst hinter der Portweiterleitung antwortet, ist ohne ausgelesenen "
                     "Reverse Proxy (Caddy) unbekannt.")

    return {"wan": {"ip": wan_ip, "type": (wan or {}).get("type", "")}, "chains": chains, "direct": direct,
            "external": external,
            "internal": internal, "ddns": ddns, "portforwards": forwards, "hints": list(dict.fromkeys(hints)),
            "portforwardsChecked": forwards_read,
            "hasData": bool(facts)}


def for_system(data: dict, system_id: str) -> list[dict]:
    """Rows "reachable via ..." for one inventory system, from an already built `build_chains` result."""
    rows: list[dict] = []
    for chain in data["chains"]:
        for path in chain["paths"]:
            if any(s["id"] == system_id for step in path["steps"] for s in step["systems"]):
                rows.append({"host": chain["host"], "scope": "extern", "via": path["sourceLabel"],
                             "status": path["status"], "mtls": path["mtls"]})
    for row in data.get("direct", []):
        if any(s["id"] == system_id for p in row["forwards"] for s in p["systems"]):
            rows.append({"host": row["host"], "scope": "extern", "via": "DNS und Portweiterleitung",
                         "status": row["status"], "mtls": row["mtls"]})
    for r in data["internal"]:
        if any(s["id"] == system_id for s in r["systems"]):
            rows.append({"host": r["host"], "scope": "intern", "via": "Traefik (TLS)", "status": "",
                         "mtls": False})
    for p in data["portforwards"]:
        if any(s["id"] == system_id for s in p["systems"]):
            rows.append({"host": f"{p['proto']} {p['wanPort']}", "scope": "portforward", "via": "Router-Portweiterleitung",
                         "status": "aktiv" if p.get("enabled", True) else "aus", "mtls": False})
    return rows[:50]
