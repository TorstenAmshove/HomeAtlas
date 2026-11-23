"""Network discovery: finds what is on the home network and gathers enough evidence about each
device that a human (or the LLM in classify.py) can say what it actually is.

Five independent sources, because no single one sees everything:

* **Ping sweep + ARP table** -- the only method that finds devices which answer nothing else. Even
  a host that ignores ICMP usually shows up in the neighbour table, because ARP resolution happens
  before the ping is sent; that is why the sweep runs even though its replies are often useless.
* **TCP port scan** -- says what a device *does*, and via `ports.DEVICE_HINTS` often what it *is*.
* **Reverse DNS** -- the router usually knows the DHCP hostnames.
* **mDNS/Bonjour and SSDP/UPnP** -- the richest source by far for consumer gear: printers, TVs,
  speakers and smart-home hubs announce their own friendly name, manufacturer and model. Where a
  UPnP device offers a description XML, that is fetched too.
* **Docker** -- see docker_probe.py.

Everything here is passive-to-mildly-active and confined to the configured subnets: connect scans,
multicast queries and HTTP GETs against the user's own equipment. Nothing authenticates, exploits
or writes.
"""
from __future__ import annotations

import asyncio
import errno
import ipaddress
import re
import shutil
import socket
import subprocess
import time
from typing import Callable

import httpx

from . import oui, ports as port_catalog, vendor_docs

ProgressFn = Callable[[str, int, str | None], None]

# Interfaces that are never the home network: loopback, Docker's own bridges, container veth
# stubs, and libvirt/VM bridges. Scanning those finds only the app's own plumbing.
_SKIP_INTERFACES = re.compile(r"^(lo|docker\d*|br-[0-9a-f]{8,}|veth|virbr|tailscale|wg\d*|zt)")

# Hard ceiling on how much address space a single scan may cover. A misconfigured /16 would mean
# 65k hosts and an effectively endless scan; /22 (1024 addresses) already takes a while.
_MAX_HOSTS_PER_SUBNET = 1024


# ---------------------------------------------------------------------------------------------
# Local network facts
# ---------------------------------------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def primary_ip() -> str:
    """The address the host would use to reach the internet -- works without any external traffic,
    since a connected UDP socket only sets up routing, it sends nothing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def _local_interface_addresses() -> list[tuple[str, ipaddress.IPv4Interface]]:
    """(interface, address) for every usable local IPv4 address -- no loopback/link-local and none
    of the virtual interfaces in `_SKIP_INTERFACES`. Empty when `ip` is unavailable."""
    found: list[tuple[str, ipaddress.IPv4Interface]] = []
    for line in _run(["ip", "-o", "-4", "addr", "show"]).splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "inet":
            continue
        interface, cidr = parts[1], parts[3]
        if _SKIP_INTERFACES.match(interface):
            continue
        try:
            address = ipaddress.IPv4Interface(cidr)
        except ValueError:
            continue
        if address.network.is_loopback or address.network.is_link_local:
            continue
        found.append((interface, address))
    return found


def local_subnets() -> list[str]:
    """IPv4 networks directly attached to this host, as CIDR strings."""
    found: list[str] = []
    for _interface, address in _local_interface_addresses():
        text = str(address.network)
        if text not in found:
            found.append(text)

    if not found:
        ip = primary_ip()
        if ip:
            found.append(str(ipaddress.ip_network(f"{ip}/24", strict=False)))
    return found


def ip_in_network(ip: str, network) -> bool:
    try:
        return ipaddress.ip_address(ip) in network
    except ValueError:
        return False


def routed_subnet_warnings(networks: list, local: list[str], silent: set[str] | None = None) -> list[str]:
    """One warning per scan network that overlaps no network directly attached to this host --
    such a network is only reachable via the gateway, so there is no ARP/MAC (hence no vendor,
    weaker identity) and no mDNS/SSDP. `networks` are ipaddress networks; `silent` holds CIDR
    strings that get a no-reply note appended. Empty `local` (interface detection failed) means
    "cannot judge" and yields nothing. See docs/multi-vlan.md."""
    local_nets = []
    for cidr in local:
        try:
            local_nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    if not local_nets:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for network in networks:
        text = str(network)
        if text in seen:
            continue
        seen.add(text)
        if any(network.version == lan.version and network.overlaps(lan) for lan in local_nets):
            continue
        note = " Keine Adresse hat geantwortet." if silent and text in silent else ""
        out.append(
            f"{text} ist nur geroutet erreichbar: keine MAC/Hersteller, kein mDNS/SSDP.{note} "
            "Siehe docs/multi-vlan.md"
        )
    return out


def _normalize_cidr(value: object) -> str | None:
    """Canonical IPv4 network string, or None for anything that is not a valid IPv4 CIDR."""
    try:
        return str(ipaddress.IPv4Network(str(value).strip(), strict=False))
    except ValueError:
        return None


def validate_scan_subnets(values: list[str]) -> list[str]:
    """Trim, drop blanks, normalise and de-duplicate free-text scan ranges (IPv4 only).

    Raises ValueError naming the first invalid entry; used by every write path for `scanSubnets`.
    """
    out: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        normalised = _normalize_cidr(text)
        if normalised is None:
            raise ValueError(f"'{text}' ist kein gültiger IPv4-Netzwerk-Bereich (Beispiel: 192.168.1.0/24).")
        if normalised not in out:
            out.append(normalised)
    return out


def selected_subnets(settings: dict, resources: list[dict]) -> list[dict]:
    """Networks the user selected for scanning, each with its origin. Pure: no db access.

    Checked controller networks first (`source="controller"`, plus `name` and `vlan`), then the
    free-text entries (`source="freitext"`, no name/vlan). `resources` are `networkResources` rows
    (kind "network"); the caller loads them. Only active + enabled resources with a valid IPv4 CIDR
    count -- a stale ID in the selection is ignored. Entries are normalised (10.0.0.5/24 ==
    10.0.0.0/24) and de-duplicated (the controller entry wins). Free text that is not a valid CIDR
    is passed through unchanged so `discover` can warn about it. Nothing selected -> `[]`; unlike
    `effective_subnets` this never falls back to the host interfaces (no subprocess).
    """
    selected = settings.get("scanControllerNetworkIds") or []
    selected = set(selected) if isinstance(selected, list) else set()
    found: list[dict] = []
    seen: set[str] = set()
    for resource in resources:
        if resource.get("id") not in selected or not resource.get("active") or not resource.get("enabled"):
            continue
        facts = resource.get("facts") or {}
        cidr = _normalize_cidr(facts.get("cidr") or "")
        if cidr and cidr not in seen:
            seen.add(cidr)
            found.append({"cidr": cidr, "source": "controller",
                          "name": resource.get("name"), "vlan": facts.get("vlanId")})
    free = settings.get("scanSubnets") or []
    for entry in free if isinstance(free, list) else []:
        entry = str(entry).strip()
        if not entry:
            continue
        entry = _normalize_cidr(entry) or entry
        if entry not in seen:
            seen.add(entry)
            found.append({"cidr": entry, "source": "freitext"})
    return found


def effective_subnets(settings: dict, resources: list[dict]) -> list[str]:
    """Networks a scan covers: `selected_subnets`, or the host's own interfaces if none selected."""
    return [e["cidr"] for e in selected_subnets(settings, resources)] or local_subnets()


def _local_interface_ips(subnets: list[str]) -> list[str]:
    """Local IPv4 addresses that lie inside one of the scanned subnets (invalid CIDRs ignored)."""
    networks = []
    for subnet in subnets:
        try:
            networks.append(ipaddress.IPv4Network(subnet, strict=False))
        except ValueError:
            continue
    ips: list[str] = []
    for _interface, address in _local_interface_addresses():
        if any(address.ip in network for network in networks) and str(address.ip) not in ips:
            ips.append(str(address.ip))
    return ips


def default_gateway() -> str:
    match = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", _run(["ip", "route", "show", "default"]))
    return match.group(1) if match else ""


def dns_servers() -> list[str]:
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as handle:
            return re.findall(r"^nameserver\s+(\S+)", handle.read(), re.MULTILINE)
    except OSError:
        return []


def arp_table() -> dict[str, str]:
    """ip -> MAC for everything in the neighbour table. Entries without a usable MAC (FAILED,
    INCOMPLETE) are dropped -- they mean "we asked and nobody answered", i.e. no device."""
    table: dict[str, str] = {}
    output = _run(["ip", "neigh", "show"])
    for line in output.splitlines():
        match = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s.*?lladdr\s+([0-9a-fA-F:]{17})\s+(\w+)", line)
        if match and match.group(3).upper() not in ("FAILED", "INCOMPLETE"):
            table[match.group(1)] = oui.normalize_mac(match.group(2))
    if table:
        return table
    # Fallback for images without iproute2.
    try:
        with open("/proc/net/arp", encoding="utf-8") as handle:
            for line in handle.readlines()[1:]:
                fields = line.split()
                if len(fields) >= 4 and fields[3] != "00:00:00:00:00:00":
                    table[fields[0]] = oui.normalize_mac(fields[3])
    except OSError:
        pass
    return table


# ---------------------------------------------------------------------------------------------
# Host liveness + port scanning
# ---------------------------------------------------------------------------------------------

async def _ping(ip: str, timeout_s: float) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(max(1, int(timeout_s))), "-n", "-q", ip,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, NotImplementedError):
        return False
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout_s + 2) == 0
    except asyncio.TimeoutError:
        proc.kill()
        return False


async def _tcp_open(ip: str, port: int, timeout_s: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout_s)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def _scan_ports(ip: str, port_list: tuple[int, ...], timeout_s: float, semaphore: asyncio.Semaphore) -> list[int]:
    async def check(port: int) -> int | None:
        async with semaphore:
            return port if await _tcp_open(ip, port, timeout_s) else None

    results = await asyncio.gather(*(check(p) for p in port_list))
    return [p for p in results if p is not None]


async def sweep_hosts(
    addresses: list[str], timeout_s: float, concurrency: int, progress: ProgressFn,
    base_pct: int, span_pct: int,
) -> dict[str, list[int]]:
    """First pass over the whole address range: ICMP plus a handful of very common TCP ports.
    Returns ip -> open liveness ports for everything that answered anything (an empty list still
    means "alive", found via ping or, later, the ARP table)."""
    semaphore = asyncio.Semaphore(concurrency)
    have_ping = shutil.which("ping") is not None
    alive: dict[str, list[int]] = {}
    done = 0
    total = max(1, len(addresses))
    # Every address in the range is probed on every liveness port, and an unused address costs the
    # full timeout on each -- so this pass gets a tighter deadline than the configured one (LAN
    # round-trips are single-digit milliseconds; the generous timeout exists for the detailed scan
    # of hosts that already answered). Combined with stopping at the first open port, a /24 stays
    # in the tens of seconds instead of minutes.
    liveness_timeout = min(timeout_s, 0.4)

    async def probe(ip: str) -> None:
        nonlocal done
        async with semaphore:
            open_ports = []
            for port in port_catalog.LIVENESS_PORTS:
                if await _tcp_open(ip, port, liveness_timeout):
                    open_ports.append(port)
                    break
            responded = bool(open_ports)
        if not responded and have_ping:
            responded = await _ping(ip, timeout_s)
        if responded:
            alive[ip] = open_ports
        done += 1
        if done % 16 == 0 or done == total:
            progress("Geräte suchen", base_pct + int(span_pct * done / total), None)

    await asyncio.gather(*(probe(ip) for ip in addresses))
    return alive


# ---------------------------------------------------------------------------------------------
# Naming: reverse DNS and HTTP banners
# ---------------------------------------------------------------------------------------------

async def reverse_dns(ip: str) -> str:
    loop = asyncio.get_running_loop()
    try:
        host, _, _ = await asyncio.wait_for(loop.run_in_executor(None, socket.gethostbyaddr, ip), timeout=3.0)
        return host
    except (OSError, asyncio.TimeoutError):
        return ""


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Only ports that are in ports.SERVICES -- others are never detected as open.
_WEB_PORTS = (443, 8443, 5001, 8006, 80, 8080, 8123, 5000, 3000, 9000, 8096, 81, 8081, 10000)


async def http_banner(ip: str, open_ports: list[int]) -> dict:
    """Title + Server header of the first web interface that answers. For consumer hardware this
    is often the single most identifying piece of evidence ("FRITZ!Box 7590", "Synology DiskStation",
    "Home Assistant")."""
    candidates = [p for p in _WEB_PORTS if p in open_ports]
    for port in candidates:
        scheme = "https" if port in (443, 8443, 5001, 8006) else "http"
        url = f"{scheme}://{ip}:{port}"
        try:
            # verify=False by design: home equipment universally uses self-signed certificates, and
            # refusing to read the banner over that would discard most of the useful evidence.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(6.0, connect=3.0), verify=False, follow_redirects=True
            ) as client:
                resp = await client.get(url)
        except (httpx.HTTPError, OSError, UnicodeDecodeError):
            continue
        title_match = _TITLE_RE.search(resp.text[:20000]) if resp.text else None
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:120] if title_match else ""
        server = resp.headers.get("server", "")[:120]
        if title or server:
            return {"url": url, "title": title, "server": server, "status": resp.status_code}
    return {}


_SHELLY_TIMEOUT = httpx.Timeout(4.0, connect=2.0)


async def shelly_identity(ip: str) -> dict | None:
    """A Shelly device's own name and exact model, read from its local API -- unlike the generic
    HTML <title> `http_banner` sees (many Shelly units all serve the literal "Shelly Web Admin",
    which is what made several genuinely different devices look like duplicates in the inventory),
    this is the one thing that actually tells them apart.

    `/shelly` answers on every generation without credentials even when the rest of the device's
    API needs a password -- Shelly designed it that way for exactly this kind of discovery, so no
    stored account is required here. Gen2+ devices then get a second, richer call for the name a
    person gave the device in the Shelly app; Gen1 keeps that name in `/settings` instead.

    Returns None for anything that doesn't answer like a Shelly at all (including "nothing on port
    80"), so a caller can safely try this against every device without first being sure."""
    try:
        async with httpx.AsyncClient(timeout=_SHELLY_TIMEOUT) as client:
            response = await client.get(f"http://{ip}/shelly")
            if response.status_code != 200:
                return None
            info = response.json()
            if not isinstance(info, dict) or not any(k in info for k in ("type", "model", "app")):
                return None

            name = None
            model = info.get("model") or info.get("type") or ""
            if int(info.get("gen") or 1) >= 2:
                try:
                    device_info = (await client.get(f"http://{ip}/rpc/Shelly.GetDeviceInfo")).json()
                    name = (device_info.get("name") or "").strip() or None
                    model = device_info.get("model") or model
                except (httpx.HTTPError, ValueError):
                    pass
            else:
                try:
                    settings = (await client.get(f"http://{ip}/settings")).json()
                    name = (settings.get("name") or "").strip() or None
                except (httpx.HTTPError, ValueError):
                    pass
            return {"name": name, "model": model, "mac": info.get("mac", "")}
    except (httpx.HTTPError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------------------------
# mDNS / Bonjour
# ---------------------------------------------------------------------------------------------

_IGMP_LIMIT_PATH = "/proc/sys/net/ipv4/igmp_max_memberships"


def _read_igmp_limit() -> str:
    """Kernel limit for multicast group memberships per socket; "" when unreadable."""
    try:
        with open(_IGMP_LIMIT_PATH, encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        return ""
    return value if value.isdigit() else ""


def _count_host_interfaces() -> int:
    return sum(1 for line in _run(["ip", "-o", "link", "show"]).splitlines() if line.strip())


def _mdns_error_hint(exc: Exception, interface_count: int) -> str:
    """Plain-language scan-log message for a failed mDNS start."""
    text = f"mDNS-Erkennung übersprungen: {exc}."
    if getattr(exc, "errno", None) != errno.ENOBUFS:
        return text
    limit = _read_igmp_limit()
    limit_text = f"net.ipv4.igmp_max_memberships = {limit}" if limit else "net.ipv4.igmp_max_memberships"
    return (
        f"{text} Der Host ist zu vielen Multicast-Gruppen beigetreten (Interfaces auf dem Host: "
        f"{interface_count}, Limit {limit_text}) -- typisch bei vielen Docker-Bridges. Abhilfe: "
        "Scan-Bereiche unter Einstellungen prüfen oder das Limit per sysctl erhöhen. "
        "Der Scan läuft ohne mDNS-Daten weiter."
    )


def _probe_mdns_blocking(
    duration: float, subnets: list[str] | None = None,
) -> tuple[dict[str, list[dict]], list[str]]:
    """Returns (results, warnings). Never raises for network errors: mDNS is best-effort."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ZeroconfServiceTypes
    except ImportError:
        return {}, []

    by_ip: dict[str, list[dict]] = {}
    warnings: list[str] = []
    kwargs: dict = {}
    if subnets:
        # Zeroconf joins the multicast group on *every* interface by default; on a host with many
        # Docker veth/bridge interfaces that exhausts igmp_max_memberships (ENOBUFS).
        ips = _local_interface_ips(subnets)
        if ips:
            kwargs["interfaces"] = ips
        else:
            warnings.append(
                "mDNS nutzt alle Interfaces des Hosts, da keins zu den Scan-Bereichen passt."
            )
    zeroconf = None
    try:
        zeroconf = Zeroconf(**kwargs)
        types = list(ZeroconfServiceTypes.find(zc=zeroconf, timeout=duration))
        if not types:
            return {}, warnings
        seen: list[tuple[str, str]] = []

        class Collector(ServiceListener):
            # Deliberately does no lookups: zeroconf documents that blocking inside a listener
            # callback stalls its event loop, so names are only recorded here and resolved after
            # the browse window closes.
            def add_service(self, _zc, type_: str, name: str) -> None:
                seen.append((type_, name))

            def update_service(self, _zc, type_: str, name: str) -> None:
                seen.append((type_, name))

            def remove_service(self, _zc, type_: str, name: str) -> None:
                pass

        browsers = [ServiceBrowser(zeroconf, type_, Collector()) for type_ in types]
        time.sleep(duration)
        for browser in browsers:
            browser.cancel()

        for type_, name in dict.fromkeys(seen):
            info = zeroconf.get_service_info(type_, name, timeout=1500)
            if info is None:
                continue
            properties = {}
            for key, value in (info.properties or {}).items():
                try:
                    properties[key.decode()] = value.decode() if isinstance(value, bytes) else value
                except (UnicodeDecodeError, AttributeError):
                    continue
            for address in info.parsed_addresses():
                by_ip.setdefault(address, []).append({
                    "type": type_,
                    "name": name.replace(f".{type_}", ""),
                    "server": (info.server or "").rstrip("."),
                    "port": info.port,
                    "properties": properties,
                })
    except (OSError, RuntimeError) as exc:
        warnings.append(_mdns_error_hint(exc, _count_host_interfaces()))
    finally:
        if zeroconf is not None:
            zeroconf.close()
    return by_ip, warnings


async def probe_mdns(
    duration: float = 5.0, subnets: list[str] | None = None,
) -> tuple[dict[str, list[dict]], list[str]]:
    return await asyncio.to_thread(_probe_mdns_blocking, duration, subnets)


# ---------------------------------------------------------------------------------------------
# SSDP / UPnP
# ---------------------------------------------------------------------------------------------

_SSDP_ADDRESS = ("239.255.255.250", 1900)
_SSDP_QUERY = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
).encode()


def _probe_ssdp_blocking(duration: float) -> dict[str, list[dict]]:
    by_ip: dict[str, list[dict]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(1.0)
    try:
        for _ in range(3):  # UDP multicast is lossy; three tries materially improves the yield
            try:
                sock.sendto(_SSDP_QUERY, _SSDP_ADDRESS)
            except OSError:
                return {}
            time.sleep(0.2)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            headers = {}
            for line in data.decode("utf-8", "replace").splitlines()[1:]:
                if ":" in line:
                    key, _, value = line.partition(":")
                    headers[key.strip().lower()] = value.strip()
            if not headers:
                continue
            entry = {
                "location": headers.get("location", ""),
                "server": headers.get("server", ""),
                "st": headers.get("st", ""),
                "usn": headers.get("usn", ""),
            }
            existing = by_ip.setdefault(ip, [])
            if not any(e["location"] == entry["location"] and e["st"] == entry["st"] for e in existing):
                existing.append(entry)
    finally:
        sock.close()
    return by_ip


_XML_TAG_RE = re.compile(r"\{[^}]*\}")


async def _fetch_upnp_description(location: str) -> dict:
    """The UPnP description XML carries `friendlyName`, `manufacturer` and `modelName` -- vendor
    self-reported and therefore the most trustworthy identification available without login."""
    import xml.etree.ElementTree as ElementTree

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0), verify=False) as client:
            resp = await client.get(location)
        if resp.status_code >= 400:
            return {}
        root = ElementTree.fromstring(resp.text)
    except (httpx.HTTPError, ElementTree.ParseError, OSError, ValueError):
        return {}

    wanted = {"friendlyName", "manufacturer", "modelName", "modelNumber", "modelDescription", "serialNumber"}
    out: dict[str, str] = {}
    for element in root.iter():
        tag = _XML_TAG_RE.sub("", element.tag)
        if tag in wanted and element.text and tag not in out:
            out[tag] = element.text.strip()[:200]
    return out


async def probe_ssdp(duration: float = 5.0) -> dict[str, list[dict]]:
    by_ip = await asyncio.to_thread(_probe_ssdp_blocking, duration)
    # Fetch each distinct description document once, not once per announcement -- a single TV can
    # answer a dozen times with the same LOCATION.
    locations = {e["location"] for entries in by_ip.values() for e in entries if e["location"]}
    fetched = await asyncio.gather(*(_fetch_upnp_description(loc) for loc in locations), return_exceptions=True)
    descriptions = {
        loc: result for loc, result in zip(locations, fetched)
        if isinstance(result, dict) and result
    }
    for entries in by_ip.values():
        for entry in entries:
            entry["description"] = descriptions.get(entry["location"], {})
    return by_ip


# ---------------------------------------------------------------------------------------------
# Assembling findings
# ---------------------------------------------------------------------------------------------

def _best_name_with_source(ip: str, hostname: str, mdns: list[dict], ssdp: list[dict], banner: dict,
                           vendor: str) -> tuple[str, str]:
    """Naming priority: what the device calls itself (UPnP friendlyName, then mDNS instance name),
    then its DNS hostname, then a web page title, then vendor + last IP octet. The fallback still
    beats a bare IP address for someone skimming the inventory.

    Returns (name, source) with source in upnp/mdns/hostname/title/vendor/ip; classify.py uses it
    to leave self-reported names alone."""
    for entry in ssdp:
        friendly = (entry.get("description") or {}).get("friendlyName")
        if friendly:
            return friendly[:80], "upnp"
    for entry in mdns:
        if entry.get("name"):
            return entry["name"][:80], "mdns"
    if hostname:
        return hostname.split(".")[0][:80], "hostname"
    if banner.get("title"):
        return banner["title"][:80], "title"
    if vendor:
        return f"{vendor.split()[0]} ({ip.rsplit('.', 1)[-1]})", "vendor"
    return ip, "ip"


def _best_name(ip: str, hostname: str, mdns: list[dict], ssdp: list[dict], banner: dict, vendor: str) -> str:
    return _best_name_with_source(ip, hostname, mdns, ssdp, banner, vendor)[0]


def _apply_shelly_name(name: str, source: str, shelly: dict) -> tuple[str, str]:
    """The name the owner gave the device in the Shelly app beats everything else and counts as
    self-reported. Without one, the exact model ("Shelly Plus 1PM") still beats the identical
    <title> every other unit serves, but is not self-reported, so the source stays unchanged."""
    if shelly.get("name"):
        return shelly["name"][:80], "shelly"
    if shelly.get("model"):
        return f"Shelly {shelly['model']}", source
    return name, source


def _guess(open_ports: list[int], mdns: list[dict], ssdp: list[dict], banner: dict,
           vendor: str) -> tuple[str, str, str, bool]:
    """Rule-based first guess of (kind, model, purpose, confident). Runs before any LLM call so the
    app is useful with no API key configured at all, and gives the LLM a baseline to correct.

    `confident` distinguishes a real identification from a filler string. Without it the LLM step
    can't tell "this is a Sonos speaker" from "something answers on a port", and would either skip
    devices that still need a real purpose or re-ask about ones already known."""
    text = " ".join([
        banner.get("title", ""), banner.get("server", ""), vendor,
        *(e.get("type", "") + " " + e.get("name", "") for e in mdns),
        *(e.get("server", "") + " " + str(e.get("description") or "") for e in ssdp),
    ]).lower()

    model = ""
    for entry in ssdp:
        description = entry.get("description") or {}
        if description.get("modelName"):
            model = " ".join(filter(None, [description.get("manufacturer", ""), description["modelName"]]))[:100]
            break

    # Product fingerprints, most specific first.
    signatures: list[tuple[tuple[str, ...], str, str, str]] = [
        (("fritz!box", "fritzbox"), "router", "AVM FRITZ!Box", "Internet-Router und WLAN-Zentrale"),
        (("fritz!repeater", "fritz!wlan"), "network", "AVM FRITZ!Repeater", "WLAN-Verstärker"),
        (("home assistant", "hassio", "_homeassistant"), "smarthome", "Home Assistant", "Smart-Home-Zentrale"),
        (("synology", "diskstation"), "nas", "Synology", "Netzwerkspeicher (NAS)"),
        (("qnap", "turbonas"), "nas", "QNAP", "Netzwerkspeicher (NAS)"),
        (("proxmox",), "server", "Proxmox VE", "Virtualisierungs-Server"),
        (("unifi", "ubiquiti"), "network", "Ubiquiti UniFi", "Netzwerk-Komponente (Access Point oder Switch)"),
        (("_printer._tcp", "_ipp._tcp", "_pdl-datastream"), "printer", "", "Netzwerkdrucker"),
        (("_googlecast._tcp", "chromecast"), "media", "Google Cast", "Streaming-Gerät oder Smart-TV"),
        (("_airplay._tcp", "_raop._tcp"), "media", "AirPlay", "Apple-Streaming-Empfänger (Apple TV, Lautsprecher oder TV)"),
        (("sonos",), "media", "Sonos", "Multiroom-Lautsprecher"),
        (("_hap._tcp", "homekit"), "smarthome", "HomeKit", "Smart-Home-Zubehör"),
        (("_esphomelib._tcp", "esphome"), "smarthome", "ESPHome", "Selbstgebautes Smart-Home-Gerät auf ESP-Basis"),
        (("shelly",), "smarthome", "Shelly", "Schaltaktor oder Messgerät im Smart Home"),
        (("tasmota",), "smarthome", "Tasmota", "Schaltaktor im Smart Home"),
        (("hue", "philips hue"), "smarthome", "Philips Hue Bridge", "Steuerzentrale für Hue-Lampen"),
        (("_ipcamera", "hikvision", "dahua", "reolink", "axis"), "camera", "", "Überwachungskamera"),
        (("openwrt",), "network", "OpenWrt", "Router oder Access Point mit OpenWrt"),
        (("plex",), "server", "Plex", "Medien-Server"),
        (("jellyfin", "emby"), "server", "Jellyfin/Emby", "Medien-Server"),
        (("pi-hole", "pihole"), "server", "Pi-hole", "Werbe- und Trackingfilter fürs ganze Netz"),
        (("nextcloud",), "server", "Nextcloud", "Private Cloud für Dateien und Kalender"),
        (("_workstation._tcp", "windows", "microsoft-iis"), "pc", "", "Computer im Netzwerk"),
        (("_smb._tcp", "samba"), "nas", "", "Gerät mit Dateifreigabe"),
        (("viessmann", "vaillant", "buderus", "wolf ", "stiebel", "daikin", "bosch thermo"),
         "heating", "", "Heizungs- oder Wärmepumpensteuerung"),
        (("fronius", "sma ", "solaredge", "kostal", "goodwe", "huawei sun"),
         "energy", "", "Wechselrichter der Photovoltaik-Anlage"),
        (("wallbox", "keba", "go-e", "easee"), "energy", "", "Ladestation für das Elektroauto"),
        (("tado", "netatmo", "homematic", "eq-3", "bosch smart"), "climate", "", "Heizungs- oder Klimasteuerung"),
    ]
    for needles, kind, model_name, purpose in signatures:
        if any(needle in text for needle in needles):
            return kind, model or model_name, purpose, True

    hint = port_catalog.hint_from_ports(open_ports)
    if hint:
        kind, model_name, purpose = hint
        return kind, model or model_name, purpose, True

    # Everything below is a placeholder, not an identification.
    if any(p in open_ports for p in (22, 3306, 5432, 2049)):
        return "server", model, "Server oder Kleinrechner im Netzwerk", False
    if open_ports:
        return "other", model, "Gerät mit Netzwerkdiensten -- Art noch nicht bestimmt", False
    return "other", model, "Gerät antwortet im Netzwerk, verrät aber keine Details", False


async def discover(settings: dict, progress: ProgressFn, extra_targets: list[str] | None = None,
                   subnets: list[str] | None = None) -> dict:
    """Runs the whole network side of a scan. Returns findings ready for the inventory plus the
    raw context (gateway, DNS, Docker) the documentation generator needs.

    `extra_targets` are individual hosts probed regardless of the configured subnets -- a router on
    a different segment (10.1.1.1 while the LAN is 192.168.1.0/24), a VM behind a bridge, anything
    routed rather than local. They get the full treatment (ping, ports, reverse DNS, banner); only
    the ARP lookup will come up empty for them, since they are not on this L2 segment.

    `subnets` is the resolved list from `effective_subnets` (the caller supplies controller
    networks from the DB); without it only the settings' free text / host interfaces are used.
    """
    warnings: list[str] = []
    timeout_s = max(0.1, settings.get("scanTimeoutMs", 700) / 1000)
    concurrency = max(8, min(512, int(settings.get("scanConcurrency", 128))))
    excluded = {ip.strip() for ip in settings.get("scanExcludeIps") or [] if ip.strip()}

    progress("Netzwerk-Bereiche ermitteln", 2, "Scan gestartet")
    if subnets is None:
        subnets = effective_subnets(settings, [])
    if not subnets:
        raise RuntimeError(
            "Es konnte kein Netzwerk-Bereich ermittelt werden. Bitte unter Einstellungen -> "
            "Netzwerk-Scan einen Bereich wie 192.168.1.0/24 eintragen."
        )

    addresses: list[str] = []
    valid_networks: list[tuple[str, ipaddress.IPv4Network | ipaddress.IPv6Network]] = []
    for subnet in subnets:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            warnings.append(f"'{subnet}' ist kein gültiger Netzwerk-Bereich und wurde übersprungen.")
            continue
        valid_networks.append((subnet, network))
        hosts = list(network.hosts())
        if len(hosts) > _MAX_HOSTS_PER_SUBNET:
            warnings.append(
                f"{subnet} umfasst {len(hosts)} Adressen -- es wurden nur die ersten "
                f"{_MAX_HOSTS_PER_SUBNET} geprüft."
            )
            hosts = hosts[:_MAX_HOSTS_PER_SUBNET]
        addresses.extend(str(h) for h in hosts if str(h) not in excluded)

    if not valid_networks:
        raise RuntimeError(
            "Es konnte kein Netzwerk-Bereich ermittelt werden (alle Einträge ungültig). Bitte unter "
            "Einstellungen -> Netzwerk-Scan einen Bereich wie 192.168.1.0/24 eintragen."
        )

    subnet_address_count = len(set(addresses))
    routed: list[str] = []
    for target in extra_targets or []:
        target = target.strip()
        if not target or target in excluded or target in addresses:
            continue
        # Hostnames are resolved here so the rest of the pipeline only ever deals with addresses.
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", target):
            try:
                target = socket.gethostbyname(target)
            except OSError:
                warnings.append(f"'{target}' ließ sich nicht auflösen und wurde übersprungen.")
                continue
            if target in addresses:
                continue
        routed.append(target)
        addresses.append(target)

    addresses = list(dict.fromkeys(addresses))
    extra_note = f" + {len(routed)} Einzelziel(e) außerhalb" if routed else ""
    progress("Geräte suchen", 5, f"{subnet_address_count} Adressen in {', '.join(subnets)}{extra_note}")

    # Phase 1 -- liveness. Multicast discovery runs concurrently: it listens for announcements
    # rather than polling, so it costs nothing to overlap with the sweep and saves ~10s.
    mdns_task = asyncio.create_task(probe_mdns(5.0, subnets)) if settings.get("scanEnableMdns", True) else None
    ssdp_task = asyncio.create_task(probe_ssdp(5.0)) if settings.get("scanEnableSsdp", True) else None

    alive = await sweep_hosts(addresses, timeout_s, concurrency, progress, 5, 30)

    # The ARP table is read *after* the sweep because the sweep is what populates it. Anything with
    # a MAC here is a real device on the local segment, even if it answered nothing.
    arp = arp_table()
    for ip, mac in arp.items():
        if ip in alive or ip not in addresses or ip in excluded:
            continue
        if mac:
            alive[ip] = []
    silent_nets = {str(n) for _s, n in valid_networks if not any(ip_in_network(ip, n) for ip in alive)}
    routed_warnings = routed_subnet_warnings([n for _s, n in valid_networks], local_subnets(), silent_nets)
    warnings.extend(routed_warnings)
    routed_texts = {w.split(" ist nur geroutet", 1)[0] for w in routed_warnings}
    for subnet, network in valid_networks:
        if str(network) in routed_texts:
            continue  # already covered by the routed-network warning
        if not any(ip_in_network(ip, network) for ip in alive):
            warnings.append(
                f"{subnet}: keine Adresse hat geantwortet (geroutetes Netz? ARP/mDNS reichen dort nicht)."
            )
    progress("Dienste prüfen", 36, f"{len(alive)} Geräte gefunden")

    # Phase 2 -- full port scan of the hosts that answered.
    semaphore = asyncio.Semaphore(concurrency)
    scanned = 0

    async def full_scan(ip: str) -> tuple[str, list[int]]:
        nonlocal scanned
        result = await _scan_ports(ip, port_catalog.ALL_PORTS, timeout_s, semaphore)
        scanned += 1
        progress("Dienste prüfen", 36 + int(24 * scanned / max(1, len(alive))), None)
        return ip, result

    port_results = dict(await asyncio.gather(*(full_scan(ip) for ip in alive)))

    # Phase 3 -- names and web banners.
    progress("Namen und Web-Oberflächen lesen", 62, None)
    hostnames = dict(zip(alive, await asyncio.gather(*(reverse_dns(ip) for ip in alive))))
    if settings.get("scanEnableHttpBanner", True):
        banner_results = await asyncio.gather(*(http_banner(ip, port_results.get(ip, [])) for ip in alive))
        banners = dict(zip(alive, banner_results))
    else:
        banners = {ip: {} for ip in alive}

    # Phase 4 -- collect the multicast results started at the beginning.
    progress("Smart-Home-Geräte abfragen (mDNS/UPnP)", 76, None)
    mdns: dict = {}
    if mdns_task:
        try:
            mdns, mdns_warnings = await mdns_task
            warnings.extend(mdns_warnings)
        except OSError as exc:
            warnings.append(_mdns_error_hint(exc, _count_host_interfaces()))
    ssdp: dict = {}
    if ssdp_task:
        try:
            ssdp = await ssdp_task
        except OSError as exc:
            warnings.append(f"UPnP/SSDP-Erkennung übersprungen: {exc}. Der Scan läuft ohne SSDP-Daten weiter.")
    for ip in list(mdns) + list(ssdp):
        # A device can announce itself over multicast without answering a single TCP port or ping.
        if ip in alive or ip in excluded:
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if any(address in net for _s, net in valid_networks):
            alive[ip] = []
            port_results.setdefault(ip, [])

    # Phase 4b -- Shelly's own local API, for the handful of devices already flagged as a Shelly
    # by vendor/banner/mDNS text above. A dedicated batch (not folded into http_banner) because it
    # asks a second, Shelly-specific question -- "what exactly are you, what did the owner call
    # you" -- that only makes sense once something already looks like a Shelly.
    shelly_candidates = [
        ip for ip in alive
        if "shelly" in " ".join([
            oui.lookup(arp.get(ip, "")), banners.get(ip, {}).get("title", ""),
            banners.get(ip, {}).get("server", ""),
            *(e.get("type", "") + " " + e.get("name", "") for e in mdns.get(ip, [])),
        ]).lower()
    ]
    shelly_identities: dict[str, dict] = {}
    if shelly_candidates:
        progress("Shelly-Geräte auslesen", 78, None)
        results = await asyncio.gather(*(shelly_identity(ip) for ip in shelly_candidates), return_exceptions=True)
        for candidate_ip, result in zip(shelly_candidates, results):
            if isinstance(result, dict) and result:
                shelly_identities[candidate_ip] = result

    gateway = default_gateway()
    findings = []
    for ip in sorted(alive, key=lambda a: ipaddress.ip_address(a)):
        open_ports = port_results.get(ip, [])
        mac = arp.get(ip, "")
        vendor = oui.lookup(mac)
        device_mdns = mdns.get(ip, [])
        device_ssdp = ssdp.get(ip, [])
        banner = banners.get(ip, {})
        hostname = hostnames.get(ip, "")

        kind, model, purpose, confident = _guess(open_ports, device_mdns, device_ssdp, banner, vendor)
        if ip == gateway:
            confident = True
            kind, purpose = "router", purpose if "Router" in purpose else "Internet-Router -- die Verbindung ins Internet läuft über dieses Gerät"

        sources = ["ping/arp"]
        if open_ports:
            sources.append("portscan")
        if device_mdns:
            sources.append("mdns")
        if device_ssdp:
            sources.append("ssdp")
        if banner:
            sources.append("http")

        name, name_source = _best_name_with_source(ip, hostname, device_mdns, device_ssdp, banner, vendor)
        shelly = shelly_identities.get(ip)
        if shelly:
            name, name_source = _apply_shelly_name(name, name_source, shelly)
            # `model` may already hold the bare vendor guess "Shelly" from `_guess`'s signature
            # table (not a real model, just a placeholder) -- the exact model code from the
            # device itself replaces that, same as it would replace an empty field.
            if shelly.get("model") and model in ("", "Shelly"):
                model = shelly["model"][:100]
        # Curated manufacturer documentation, matched across everything known about the device.
        # Anything not covered here is left to the LLM in classify.py, whose suggestions are
        # link-checked before they are stored.
        _, doc_url = vendor_docs.lookup(vendor, model, name, banner.get("title", ""), banner.get("server", ""))

        findings.append({
            "discoveryKey": f"mac:{mac}" if mac else f"ip:{ip}",
            "kind": kind,
            "name": name,
            "hostname": hostname,
            "ip": ip,
            "mac": mac,
            "vendor": vendor,
            "model": model,
            "purpose": purpose,
            "url": banner.get("url", ""),
            "docUrl": doc_url,
            "status": "online",
            "importance": "critical" if ip == gateway else "normal",
            "discovered": 1,
            "discoverySource": "+".join(sources),
            "openPorts": open_ports,
            "services": port_catalog.describe_ports(open_ports),
            "extra": {
                "mdns": device_mdns,
                "ssdp": device_ssdp,
                "httpBanner": banner,
                "randomizedMac": oui.is_locally_administered(mac),
                "isGateway": ip == gateway,
                "routedTarget": ip in routed,
                "guessConfident": confident,
                "nameSource": name_source,
            },
        })

    # Name disambiguation (several devices sharing one generic name, e.g. many Shelly units all
    # serving the literal <title>"Shelly Web Admin"</title>) happens once in pipeline.py, on the
    # final merged+classified findings list -- doing it here would just get overwritten by
    # classify.apply()'s own (possibly just as generic) name suggestion a few steps later.

    return {
        "findings": findings,
        "subnets": subnets,
        "gateway": gateway,
        "dnsServers": dns_servers(),
        "hostIp": primary_ip(),
        "warnings": warnings,
        "routedTargets": routed,
        "counts": {
            "addressesScanned": len(addresses),
            "devicesFound": len(findings),
            "withMdns": sum(1 for f in findings if f["extra"]["mdns"]),
            "withSsdp": sum(1 for f in findings if f["extra"]["ssdp"]),
            "routedFound": sum(1 for f in findings if f["extra"]["routedTarget"]),
        },
    }
