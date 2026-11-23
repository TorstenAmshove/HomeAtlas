"""The full scan: probe the network, merge into the inventory, let the LLM identify the leftovers,
then rewrite the documentation.

Runs as a background task with progress written to the `scans` row, because a /24 sweep takes
minutes and the browser must not hold a request open that long. Every phase is individually
non-fatal apart from discovery itself: a missing Docker socket, a failed LLM call or a broken
documentation run each degrade to a warning on the scan, so a scan never ends with nothing to show.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import traceback

import ipaddress
from datetime import datetime, timedelta, timezone

from . import (
    fritz_wan,
    adguard_probe, classify, cloudflare_probe, crypto, db, diagnostics, discovery, docker_probe, docs,
    exposure_files, firewall_nft, firewall_unifi, omada_probe, oui, probe_auth, proxmox_probe, public_dns, traefik_probe,
    unifi_classic_probe, unifi_probe,
)


def _extra_targets(settings: dict, subnets_hint: list[str]) -> list[str]:
    """Hosts to probe that the subnet sweep would never reach.

    Two sources. Explicitly configured targets (Einstellungen -> Netzwerk-Scan), and the addresses
    of devices someone already entered by hand (`discovered == 0`; devices a scan or a controller
    API found are skipped -- they arrive through their own source) -- a router at 10.1.1.1 while the LAN is
    192.168.1.0/24, or a VM behind a bridge. Without this, a hand-created entry could never be
    enriched: it would sit in the inventory with a name and nothing else forever.
    """
    targets: list[str] = [t.strip() for t in (settings.get("scanExtraTargets") or []) if t.strip()]

    networks = []
    for subnet in subnets_hint:
        try:
            networks.append(ipaddress.ip_network(subnet, strict=False))
        except ValueError:
            continue

    for system in db.list_systems():
        if system.get("discovered"):
            continue
        address = (system.get("ip") or "").strip()
        if not address or address in targets:
            continue
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        # Inside a scanned subnet it is covered already; outside it needs to be named explicitly.
        if not any(parsed in network for network in networks):
            targets.append(address)
    return targets


async def _probe_with_credentials(log) -> tuple[int, list[str], dict[str, str], list[dict]]:
    """Logs into the devices whose stored credentials were explicitly cleared for it and records
    what it read. Strictly read-only -- see probe_auth.

    Facts learned here are written into `extra.probe` for display, and are additionally used to
    fill `purpose`, `os` and `model` **only where those are still empty**. An authenticated read is
    more authoritative than a port guess, but it must not overwrite what a human typed.

    The third return value is every IP->MAC pair read from a router's own ARP/host-list table
    (see probe_auth.extract_arp_entries) -- routers only, since that is the one place such a table
    covers the whole LAN rather than just what this host itself could see. The fourth is every
    printer toner/ink reading Home Assistant reported (see probe_auth.extract_printer_supplies) --
    gathered from whichever system the HA credential is attached to (usually the smart-home hub,
    not a printer itself), which is why matching them to a printer happens separately afterwards.
    """
    warnings: list[str] = []
    probed = 0
    learned_arp: dict[str, str] = {}
    printer_supplies: list[dict] = []
    settings = db.get_settings()
    used_fallback = 0

    for system in db.list_systems():
        accounts = db.list_probe_accounts(system["id"])
        if not accounts:
            # Only where nothing device-specific is stored, and only where probe_auth's guardrails
            # allow it (right kind of device, matching port actually open).
            fallback = probe_auth.fallback_account(settings, system)
            if fallback is None:
                continue
            accounts = [fallback]
            used_fallback += 1
        try:
            outcome = await probe_auth.probe_system(system, accounts)
        except Exception as exc:  # noqa: BLE001 -- one unreachable device must not end the scan
            warnings.append(f"Abfrage von {system['name']} fehlgeschlagen: {exc}")
            db.add_device_error_event(system["id"], "error", f"Abfrage fehlgeschlagen: {exc}")
            continue

        # Collected regardless of whether *some* credential on this system succeeded -- a system
        # with both a working SSH account and a Home Assistant account whose token just expired
        # used to have that second failure silently swallowed here (only visible at all once every
        # credential on the row failed), which is exactly backwards for something an admin needs
        # to notice and fix. Logged both to the scan-wide `warnings` (gone after the next scan) and
        # against the device itself (see db.add_device_error_event) -- someone troubleshooting one
        # specific switch/host should not have to dig through the last scan's log to find out an
        # SSH timeout is why its config backup stopped updating.
        for label, result in (outcome.get("results") or {}).items():
            if not result.get("ok") and result.get("error"):
                warnings.append(f"{system['name']} ({label}): {result['error']}")
                db.add_device_error_event(system["id"], "error", f"{label}: {result['error']}")
            # Set even on an otherwise-ok result (e.g. probe_ssh's per-command timeouts) -- a
            # switch whose config export timed out while its other commands succeeded still needs
            # that specific failure visible on the device, not just buried in an overall "ok".
            for warning in result.get("warnings") or []:
                db.add_device_error_event(system["id"], "warning", f"{label}: {warning}")
        if not outcome["ran"]:
            continue

        # Config exports go only into encrypted deviceConfigVersions (persist_config_backups below),
        # never into extra.probe, which members, the docs and the LLM can read.
        patch: dict = {"extra": {**(system.get("extra") or {}),
                                 "probe": probe_auth.without_config_backups(outcome["results"])}}
        if outcome.get("purpose") and not system.get("purpose"):
            patch["purpose"] = outcome["purpose"]

        facts = {key: value["value"] for result in outcome["results"].values() if result.get("ok")
                 for key, value in result.get("facts", {}).items()}
        if facts.get("os") and not system.get("os"):
            patch["os"] = facts["os"].splitlines()[0][:120]
        if facts.get("model") and not system.get("model"):
            patch["model"] = facts["model"].strip()[:100]
        if facts.get("modelName") and not system.get("model"):
            patch["model"] = facts["modelName"].strip()[:100]

        db.update_system(system["id"], patch)
        probed += 1
        log(f"Abgefragt: {system['name']} ({', '.join(outcome['results'])})")
        if probe_auth.persist_config_backups(system, outcome):
            log(f"Konfiguration von {system['name']} gesichert")
        if system.get("kind") == "router":
            learned_arp.update(probe_auth.extract_arp_entries(outcome))
        printer_supplies += probe_auth.extract_printer_supplies(outcome)

    if used_fallback:
        log(f"Standard-Zugang bei {used_fallback} Gerät(en) ohne eigenen Zugang versucht")
    return probed, warnings, learned_arp, printer_supplies


async def _learn_devices_from_arp(learned_arp: dict[str, str], log) -> int:
    """Adds inventory entries for IP/MAC pairs a router's own ARP or host-list table revealed that
    the network sweep itself never saw -- a sleeping device, one behind a firewall that blocks the
    scan's own pings/port probes, or simply on a segment this host can reach an SSH/TR-064
    credential for but not ping directly. Each new entry gets the same reverse-DNS naming
    discovery.py already gives every device it finds itself, rather than sitting unnamed until a
    later full scan happens to rediscover it on its own.
    """
    if not learned_arp:
        return 0
    known_macs = {s["mac"] for s in db.list_systems() if s.get("mac")}
    known_ips = {s["ip"] for s in db.list_systems() if s.get("ip")}
    new_pairs = {ip: mac for ip, mac in learned_arp.items()
                 if mac not in known_macs and ip not in known_ips}
    if not new_pairs:
        return 0

    hostnames = dict(zip(new_pairs, await asyncio.gather(
        *(discovery.reverse_dns(ip) for ip in new_pairs))))
    for ip, mac in new_pairs.items():
        vendor = oui.lookup(mac)
        hostname = hostnames.get(ip, "")
        name = (hostname.split(".")[0][:80] if hostname
                else f"{vendor.split()[0]} ({ip.rsplit('.', 1)[-1]})" if vendor else ip)
        db.upsert_discovered_system({
            "discoveryKey": f"mac:{mac}",
            "kind": "other",
            "name": name,
            "hostname": hostname,
            "ip": ip,
            "mac": mac,
            "vendor": vendor,
            "purpose": ("Über die ARP-/Host-Tabelle des Gateways gefunden, aber noch nicht "
                        "vollständig eingeordnet -- der nächste Netzwerk-Scan füllt den Rest, "
                        "sobald das Gerät selbst antwortet."),
            "status": "online",
            "importance": "normal",
            "discovered": 1,
            "discoverySource": "gateway-arp",
            "openPorts": [],
            "services": [],
            "extra": {"randomizedMac": oui.is_locally_administered(mac), "guessConfident": False},
        })
    log(f"{len(new_pairs)} weitere(s) Gerät(e) über die ARP-/Host-Tabelle des Gateways gefunden")
    return len(new_pairs)


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(*parts: str) -> set[str]:
    return {w for p in parts for w in _WORD_RE.findall(p.lower()) if len(w) >= 3}


def _match_printer_supplies(supplies: list[dict], printers: list[dict]) -> dict[str, list[dict]]:
    """Groups toner/ink readings by which printer in the inventory they most likely belong to.

    Home Assistant's own printer name is the only link back to the inventory -- there is no shared
    ID between "what HA calls it" and "what this app calls it" -- so this is a best-effort token
    overlap between the HA sensor's friendly name and each printer's name/vendor/model, not an
    exact match. A household with exactly one printer skips the guessing entirely and attaches
    everything to it, since that is by far the common case and token matching has the most room to
    fail on a printer named something HA's own device name shares no words with at all.
    """
    if not supplies or not printers:
        return {}
    if len(printers) == 1:
        return {printers[0]["id"]: supplies}

    printer_tokens = [(p["id"], _tokens(p.get("name", ""), p.get("vendor", ""), p.get("model", "")))
                       for p in printers]
    by_printer: dict[str, list[dict]] = {}
    for supply in supplies:
        supply_tokens = _tokens(supply["name"])
        best_id, best_overlap = None, 0
        for printer_id, tokens in printer_tokens:
            overlap = len(supply_tokens & tokens)
            if overlap > best_overlap:
                best_id, best_overlap = printer_id, overlap
        if best_id:
            by_printer.setdefault(best_id, []).append(supply)
    return by_printer


def _apply_printer_supplies(printer_supplies: list[dict], log) -> int:
    """Persists matched toner/ink readings onto each printer's own `extra.printerSupplies`, so
    SystemDetailPage can render them at the device they actually belong to instead of only in the
    generic facts block of whatever system holds the Home Assistant credential."""
    printers = [s for s in db.list_systems() if s["kind"] == "printer"]
    by_printer = _match_printer_supplies(printer_supplies, printers)
    for printer_id, supplies in by_printer.items():
        printer = db.get_system(printer_id)
        if printer is None:
            continue
        db.update_system(printer_id, {"extra": {**(printer.get("extra") or {}), "printerSupplies": supplies}})
    if by_printer:
        log(f"Verbrauchsmaterial-Stand für {len(by_printer)} Drucker aus Home Assistant übernommen")
    return len(by_printer)


def _assign_proxmox_parents(guests: list[dict], fallback_host_id: str | None) -> None:
    """Points each Proxmox guest's `parentId` at its own node's system row, so a guest ends up
    nested under the node it actually runs on rather than always under whichever single host the
    credential happens to be attached to -- the credential is attached to *one* HomeAtlas system
    row, but a cluster can run guests across several nodes at several addresses.

    Matched by hostname/name against the guest's own `extra.proxmox.node` (set by
    proxmox_probe.probe) -- the same "known name, no shared id" situation `_match_printer_supplies`
    above already deals with, just for hosts instead of printers. Falls back to the credential's
    own host when no separate row for that node exists yet, which is also the correct answer for
    the common single-node setup (there, every guest's node *is* that one host).
    """
    node_hosts = {
        (s.get("hostname") or s.get("name") or "").strip().lower(): s["id"]
        for s in db.list_systems() if s["kind"] in ("server", "nas")
    }
    for guest in guests:
        node = ((guest.get("extra") or {}).get("proxmox") or {}).get("node", "")
        guest["parentId"] = node_hosts.get(node.strip().lower()) or fallback_host_id


def _link_omada_topology() -> int:
    """Resolves each Omada finding's `extra.omada.uplinkMac` (set by omada_probe.py, on APs,
    switches and clients alike) to the inventory id of the device it points at, and records that
    as `parentId`. Can only happen after the whole batch is upserted -- the target device's own
    row might not have existed a moment earlier in the very same scan -- which is why this is a
    separate pass rather than something omada_probe.py could set directly. topology.py's network
    section then chains by `parentId` the same way the router chain already does, so an AP or
    client shows up under the switch/AP it is actually plugged/associated into instead of a flat,
    unordered row.
    """
    systems = db.list_systems()
    by_mac = {s["mac"]: s["id"] for s in systems if s.get("mac")}
    linked = 0
    for system in systems:
        uplink_mac = ((system.get("extra") or {}).get("omada") or {}).get("uplinkMac")
        if not uplink_mac:
            continue
        target_id = by_mac.get(uplink_mac)
        if not target_id or target_id == system["id"] or system.get("parentId") == target_id:
            continue
        db.update_system(system["id"], {"parentId": target_id})
        linked += 1
    return linked


def _link_unifi_topology() -> int:
    """Resolve controller-local UniFi IDs to inventory parent IDs after all findings are upserted."""
    systems = db.list_systems()
    by_device_id = {
        unifi.get("deviceId"): system["id"]
        for system in systems
        if (unifi := ((system.get("extra") or {}).get("unifi") or {})).get("deviceId")
    }
    linked = 0
    for system in systems:
        unifi = (system.get("extra") or {}).get("unifi") or {}
        target_id = by_device_id.get(unifi.get("uplinkDeviceId"))
        if not target_id or target_id == system["id"] or system.get("parentId") == target_id:
            continue
        db.update_system(system["id"], {"parentId": target_id})
        linked += 1
    return linked


def _make_names_unique(findings: list[dict]) -> None:
    """Disambiguates names shared by several distinct devices in this scan.

    A name shared by several devices reads as duplicates in the inventory even though each one is
    a real, separate device with its own MAC/IP/discovery key -- some devices (many Shelly units,
    for one) serve the exact same generic <title> on their local web UI, and the LLM step can
    independently suggest the same generic name for visually-identical devices. Run once, after
    every source and the LLM step have had their say -- doing it earlier just gets overwritten.

    Docker containers all share their host's IP, so the IP-octet suffix means nothing for them
    (their names already carry project and service). Only an exact duplicate on the same host
    (e.g. `docker compose --scale`) gets a running counter. The same counter applies to any
    other finding without an IP, where no octet suffix is possible.
    """
    name_counts: dict[str, int] = {}
    for f in findings:
        name_counts[f["name"]] = name_counts.get(f["name"], 0) + 1
    # The running count within the (name, suffix) group keeps every entry unique even when two
    # devices end up with the same name and the same last IP octet.
    group_counts: dict[tuple[str, str], int] = {}
    for f in findings:
        if name_counts[f["name"]] <= 1:
            continue
        if "docker" in (f.get("extra") or {}) or not f.get("ip"):
            key = (f["name"], "")
            group_counts[key] = group_counts.get(key, 0) + 1
            if group_counts[key] > 1:
                f["name"] = f"{f['name']} ({group_counts[key]})"
        elif f.get("ip"):
            suffix = f["ip"].rsplit(".", 1)[-1]
            group_counts[(f["name"], suffix)] = group_counts.get((f["name"], suffix), 0) + 1
            occurrence = group_counts[(f["name"], suffix)]
            f["name"] = f"{f['name']} ({suffix}{f'-{occurrence}' if occurrence > 1 else ''})"


async def _classify_new_findings(findings: list[dict], settings: dict, log) -> tuple[list[dict], list[str]]:
    """LLM classification only for findings the inventory doesn't know yet (the upsert would
    create them). Known devices are skipped -- repeating the question every scan costs tokens and
    the first answer is kept by the upsert (see `upsert_discovered_system`). A device that could
    not be classified on its first scan is not retried automatically; the admin button does that."""
    new = [f for f in findings if db.find_existing_for_discovery(f)[0] is None]
    known = len(findings) - len(new)
    if not new:
        log(f"KI-Einordnung: 0 neue Funde, {known} bekannte übersprungen")
        return findings, []
    classifications, warnings = await classify.classify(new, settings, log)
    new_ids = {id(f) for f in new}
    applied = 0
    result = []
    for f in findings:
        if id(f) in new_ids and f.get("ip") in classifications:
            f = classify.apply(f, classifications[f["ip"]])
            applied += 1
        result.append(f)
    log(f"KI-Einordnung: {len(new)} neue Funde, {applied} eingeordnet, {known} bekannte übersprungen")
    return result, warnings



async def _label_providers(facts: list[dict]) -> None:
    """Fills `provider` of Cloudflare A/AAAA records with the reverse-DNS name of the target (a
    label for "Extern gehostet" only; no answer leaves it empty)."""
    targets = sorted({f["data"]["target"] for f in facts if f["kind"] == "cf_dns" and f["data"]["type"] in ("A", "AAAA")})[:30]
    names: dict[str, str] = {}
    for ip in targets:
        try:
            names[ip] = (await diagnostics.reverse_dns(ip)).get("hostname", "")[:100]
        except Exception:
            names[ip] = ""
    for f in facts:
        if f["kind"] == "cf_dns":
            f["data"]["provider"] = names.get(f["data"]["target"], "")

async def run_full_scan(scan_id: str) -> None:
    settings = db.get_settings()
    warnings: list[str] = []
    created = updated = 0
    unifi_results: list[tuple[dict, dict]] = []

    highest = 0

    def progress(phase: str, percent: int, log_line: str | None = None) -> None:
        # Clamped: the bar never moves backwards, even if a later phase reports a lower value.
        nonlocal highest
        highest = max(highest, percent)
        db.update_scan(scan_id, phase=phase, progress=highest, log_line=log_line)

    def log(line: str) -> None:
        db.update_scan(scan_id, log_line=line)

    try:
        # The vendor database makes every later step better (it feeds the rule-based guess and the
        # LLM's evidence), so it is refreshed first -- but never at the cost of the scan.
        if not oui.is_downloaded() and not oui.download_due():
            log("Hersteller-Datenbank: letzter Versuch vor weniger als 24 h, nächster Versuch später")
        elif not oui.is_downloaded():
            progress("Hersteller-Datenbank laden", 1, "Lade IEEE-Herstellerdatenbank")
            ok, message = await oui.refresh_from_ieee()
            log(f"Hersteller-Datenbank: {message}")
            if not ok:
                warnings.append(f"Hersteller-Datenbank nicht geladen: {message}")

        configured_subnets = discovery.effective_subnets(
            settings, db.list_network_resources(kind="network", active_only=True))
        extra = _extra_targets(settings, configured_subnets)
        if extra:
            log(f"Zusätzliche Einzelziele außerhalb der Bereiche: {', '.join(extra[:10])}")

        result = await discovery.discover(
            settings, progress, extra_targets=extra, subnets=configured_subnets)
        findings = result["findings"]
        for w in result["warnings"]:
            log(w)
        warnings += result["warnings"]

        if settings.get("scanEnableDocker", True):
            progress("Container erfassen", 86, "Frage Docker ab")
            docker_result = await docker_probe.probe(result.get("hostIp", ""))
            if docker_result["ok"]:
                findings += docker_result["systems"]
                log(f"Docker: {len(docker_result['systems'])} Container gefunden")
                db.replace_exposure_facts("docker_ddns", "docker", docker_result.get("ddns") or [])
            elif docker_probe.socket_available():
                warnings.append(docker_result["error"])
                db.mark_exposure_facts_stale("docker_ddns", "docker")
            else:
                log("Docker-Socket nicht eingebunden -- Container werden übersprungen")
        else:
            db.delete_exposure_facts(source="docker_ddns")

        if settings.get("scanEnableUnifi", True):
            unifi_accounts = [a for a in db.list_accounts()
                              if a.get("category") == "unifi" and a.get("allowProbe")]
            if unifi_accounts:
                progress("UniFi-Geräte erfassen", 87, "Frage UniFi Network Controller ab")
            for account in unifi_accounts:
                api_key = crypto.decrypt(account.get("secretEnc") or "")
                unifi_result = await unifi_probe.probe(
                    account.get("url") or "", api_key, account["id"], account.get("systemId"),
                    client_subnets=configured_subnets,
                )
                if unifi_result["ok"]:
                    findings += unifi_result["systems"]
                    unifi_results.append((account, unifi_result))
                    log(f"UniFi ({account['label']}): {len(unifi_result['systems'])} Geräte/Clients gefunden"
                        + (f", {unifi_result['skippedClients']} Clients außerhalb der Scan-Netze übersprungen"
                           if unifi_result.get("skippedClients") else ""))
                    for warning in unifi_result["warnings"]:
                        warnings.append(warning)
                        if account.get("systemId"):
                            db.add_device_error_event(account["systemId"], "warning", warning)
                else:
                    warnings.append(f"UniFi Controller ({account['label']}): {unifi_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", unifi_result["error"])

        if settings.get("scanEnableOmada", True):
            omada_accounts = [a for a in db.list_accounts()
                              if a.get("category") == "omada" and a.get("allowProbe")]
            if omada_accounts:
                progress("Omada-Geräte erfassen", 87, "Frage Omada Controller ab")
            for account in omada_accounts:
                client_id = account.get("username") or ""
                client_secret = crypto.decrypt(account.get("secretEnc") or "")
                omada_result = await omada_probe.probe(account.get("url") or "", client_id, client_secret)
                if omada_result["ok"]:
                    findings += omada_result["systems"]
                    log(f"Omada ({account['label']}): {len(omada_result['systems'])} Geräte/Clients gefunden")
                else:
                    warnings.append(f"Omada Controller ({account['label']}): {omada_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", omada_result["error"])

        if settings.get("scanEnableProxmox", True):
            proxmox_accounts = [a for a in db.list_accounts()
                               if a.get("category") == "proxmox" and a.get("allowProbe")]
            if proxmox_accounts:
                progress("Proxmox-Gäste erfassen", 88, "Frage Proxmox-Host ab")
            for account in proxmox_accounts:
                token_id = account.get("username") or ""
                token_secret = crypto.decrypt(account.get("secretEnc") or "")
                proxmox_result = await proxmox_probe.probe(account.get("url") or "", token_id, token_secret)
                if proxmox_result["ok"]:
                    _assign_proxmox_parents(proxmox_result["systems"], account.get("systemId"))
                    findings += proxmox_result["systems"]
                    log(f"Proxmox ({account['label']}): {len(proxmox_result['systems'])} Gäste gefunden")
                else:
                    warnings.append(f"Proxmox-Host ({account['label']}): {proxmox_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", proxmox_result["error"])

        if settings.get("scanEnableAdguard", True):
            adguard_accounts = [a for a in db.list_accounts()
                                if a.get("category") == "adguard" and a.get("allowProbe")]
            if adguard_accounts:
                progress("AdGuard Home erfassen", 88, "Frage AdGuard Home ab")
            for account in adguard_accounts:
                username = account.get("username") or ""
                password = crypto.decrypt(account.get("secretEnc") or "")
                adguard_result = await adguard_probe.probe(account.get("url") or "", username, password)
                if adguard_result["ok"]:
                    findings += adguard_result["systems"]
                    log(f"AdGuard Home ({account['label']}): {len(adguard_result['systems'])} "
                        "Client(s)/Lease(s) übernommen")
                    if account.get("systemId") and adguard_result.get("stats"):
                        host = db.get_system(account["systemId"])
                        if host is not None:
                            db.update_system(account["systemId"], {
                                "extra": {**(host.get("extra") or {}), "adguard": adguard_result["stats"]},
                            })
                else:
                    warnings.append(f"AdGuard Home ({account['label']}): {adguard_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", adguard_result["error"])

        classic_wans: list[tuple[str, list[dict]]] = []
        if settings.get("scanEnableUnifiClassic", True):
            # Same accounts as the integration-API scan above: one UniFi API key serves both (ADR-0016).
            classic_accounts = [a for a in db.list_accounts()
                                if a.get("category") == "unifi" and a.get("allowProbe")]
            if classic_accounts:
                progress("UniFi-Portweiterleitungen erfassen", 88, "Frage klassische UniFi-API ab")
            for account in classic_accounts:
                try:
                    classic = await asyncio.wait_for(unifi_classic_probe.probe(
                        account.get("url") or "", crypto.decrypt(account.get("secretEnc") or ""),
                        account["id"], account.get("systemId")), timeout=60)
                except Exception as exc:  # one failing source must never stop the scan
                    classic = {"ok": False, "error": f"UniFi (klassisch): {type(exc).__name__}"}
                if classic["ok"]:
                    db.replace_exposure_facts("unifi_classic", account["id"],
                                              classic["forwards"] + (classic.get("wanFacts") or []))
                    classic_wans.append((account["id"], classic.get("wans") or []))
                    warnings += [f"UniFi klassisch ({account['label']}): {w}" for w in classic.get("warnings") or []]
                    log(f"UniFi klassisch ({account['label']}): {len(classic['forwards']) - 1} Portweiterleitung(en) gelesen")
                else:
                    db.mark_exposure_facts_stale("unifi_classic", account["id"])
                    warnings.append(f"UniFi klassisch ({account['label']}): {classic['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", classic["error"])
            db.prune_exposure_facts("unifi_classic", [a["id"] for a in classic_accounts])
        else:
            db.delete_exposure_facts(source="unifi_classic")

        # Optional second opinion on the public address (ADR-0018); UniFi works without it.
        fritz_ip = ""
        fritz_targets: dict[str, tuple[dict, dict]] = {}
        if settings.get("scanUseCredentials", True):
            for account in db.list_accounts():
                target = db.get_system(account["systemId"]) if account.get("allowProbe") and account.get("systemId") else None
                label = " ".join(str((target or {}).get(k) or "") for k in ("name", "hostname", "vendor", "model")).lower()
                if target and target.get("ip") and "fritz" in label:
                    fritz_targets.setdefault(target["id"], (account, target))
        for account, target in fritz_targets.values():
            try:
                fritz = await asyncio.wait_for(fritz_wan.probe(target["ip"]), timeout=15)
            except Exception as exc:  # one failing source must never stop the scan
                fritz = {"ok": False, "ip": "", "error": f"FRITZ!Box: {type(exc).__name__}"}
            if fritz["ok"]:
                db.replace_exposure_facts("fritzbox", account["id"], [
                    {"kind": "wan_address", "key": "fritzbox", "data": {"ip": fritz["ip"], "source": "FRITZ!Box"}}])
                fritz_ip = fritz_ip or fritz["ip"]
                log(f"FRITZ!Box ({target['name']}): öffentliche Adresse gelesen")
            else:
                db.mark_exposure_facts_stale("fritzbox", account["id"])
                warnings.append(f"FRITZ!Box ({target['name']}): {fritz['error']}")
        db.prune_exposure_facts("fritzbox", [account["id"] for account, _ in fritz_targets.values()])

        # Firewall zones/policies/groups (ADR-0017): off by default, same UniFi accounts as above.
        if settings.get("scanEnableFirewallUnifi", False):
            fw_accounts = [a for a in db.list_accounts()
                           if a.get("category") == "unifi" and a.get("allowProbe")]
            if fw_accounts:
                progress("UniFi-Firewall erfassen", 88, "Lese Firewall-Zonen und -Regeln")
            for account in fw_accounts:
                try:
                    fw = await asyncio.wait_for(firewall_unifi.probe(
                        account.get("url") or "", crypto.decrypt(account.get("secretEnc") or ""),
                        account["id"], account.get("systemId")), timeout=60)
                except Exception as exc:  # one failing source must never stop the scan
                    fw = {"ok": False, "error": f"UniFi-Firewall: {type(exc).__name__}"}
                if fw["ok"]:
                    db.replace_firewall_facts("unifi", account["id"], fw["facts"])
                    log(f"UniFi-Firewall ({account['label']}): "
                        f"{sum(1 for f in fw['facts'] if f['kind'] == 'policy')} Regel(n) gelesen")
                else:
                    db.mark_firewall_facts_stale("unifi", account["id"])
                    warnings.append(f"UniFi-Firewall ({account['label']}): {fw['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", fw["error"])
            db.prune_firewall_facts("unifi", [a["id"] for a in fw_accounts])
        else:
            db.delete_firewall_facts(source="unifi")

        # nftables of released hosts (ADR-0017): off by default, one fixed sudo command per host.
        if settings.get("scanEnableFirewallNft", False):
            nft_accounts = [a for a in db.list_accounts()
                            if a.get("category") == firewall_nft.CATEGORY and a.get("allowProbe")]
            if nft_accounts:
                progress("Host-Firewalls erfassen", 88, "Lese nftables-Regelsätze")
            for account in nft_accounts:
                target = db.get_system(account["systemId"]) if account.get("systemId") else None
                host = ((target or {}).get("ip") or "").strip()
                try:
                    nft = await asyncio.wait_for(firewall_nft.probe(host, account), timeout=60)
                except Exception as exc:  # one failing host must never stop the scan
                    nft = {"ok": False, "facts": [], "error": f"nftables: {type(exc).__name__}"}
                if nft["ok"]:
                    db.replace_firewall_facts(firewall_nft.SOURCE, account["id"], nft["facts"])
                    log(f"nftables ({account['label']}): {max(len(nft['facts']) - 1, 0)} Kette(n) gelesen")
                else:
                    db.mark_firewall_facts_stale(firewall_nft.SOURCE, account["id"])
                    warnings.append(f"nftables ({account['label']}): {nft['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", nft["error"])
            db.prune_firewall_facts(firewall_nft.SOURCE, [a["id"] for a in nft_accounts])
        else:
            db.delete_firewall_facts(source=firewall_nft.SOURCE)

        if settings.get("scanEnableTraefik", True):
            traefik_accounts = [a for a in db.list_accounts()
                                if a.get("category") == "traefik" and a.get("allowProbe")]
            if traefik_accounts:
                progress("Traefik erfassen", 88, "Frage Traefik-API ab")
            for account in traefik_accounts:
                username = account.get("username") or ""
                password = crypto.decrypt(account.get("secretEnc") or "")
                try:
                    traefik_result = await asyncio.wait_for(
                        traefik_probe.probe(account.get("url") or "", username, password), timeout=60)
                except Exception as exc:  # one failing source must never stop the scan
                    traefik_result = {"ok": False, "facts": [], "error": f"Traefik: {type(exc).__name__}"}
                if traefik_result["ok"]:
                    db.replace_exposure_facts("traefik", account["id"], traefik_result["facts"])
                    log(f"Traefik ({account['label']}): {len(traefik_result['facts'])} Route(n) gelesen")
                else:
                    db.mark_exposure_facts_stale("traefik", account["id"])
                    warnings.append(f"Traefik ({account['label']}): {traefik_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", traefik_result["error"])
            db.prune_exposure_facts("traefik", [a["id"] for a in traefik_accounts])
        else:
            db.delete_exposure_facts(source="traefik")

        if settings.get("scanEnableExposureFiles", True):
            file_accounts = [a for a in db.list_accounts()
                             if a.get("category") in exposure_files.CATEGORIES and a.get("allowProbe")]
            if file_accounts:
                progress("Konfigurationen erfassen", 88, "Lese cloudflared-, Caddy- und ddclient-Konfiguration")
            for account in file_accounts:
                source = exposure_files.CATEGORIES[account["category"]]
                target = db.get_system(account["systemId"]) if account.get("systemId") else None
                host = ((target or {}).get("ip") or "").strip()
                try:
                    file_result = await asyncio.wait_for(
                        exposure_files.probe(source, host, account, via=host), timeout=60)
                except Exception as exc:  # one failing source must never stop the scan
                    file_result = {"ok": False, "facts": [], "error": f"{source}: {type(exc).__name__}"}
                if file_result["ok"]:
                    db.replace_exposure_facts(source, account["id"], file_result["facts"])
                    log(f"{source} ({account['label']}): {len(file_result['facts'])} Eintrag/Einträge gelesen")
                else:
                    db.mark_exposure_facts_stale(source, account["id"])
                    warnings.append(f"{source} ({account['label']}): {file_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", file_result["error"])
            for source in exposure_files.CATEGORIES.values():
                db.prune_exposure_facts(source, [a["id"] for a in file_accounts
                                                 if exposure_files.CATEGORIES[a["category"]] == source])
        else:
            for source in exposure_files.CATEGORIES.values():
                db.delete_exposure_facts(source=source)

        if settings.get("scanEnableCloudflare", False):
            cf_accounts = [a for a in db.list_accounts()
                           if a.get("category") == "cloudflare" and a.get("allowProbe")]
            if cf_accounts:
                progress("Cloudflare erfassen", 88, "Frage Cloudflare-API ab")
            for account in cf_accounts:
                try:
                    cf_result = await asyncio.wait_for(cloudflare_probe.probe(
                        account.get("url") or "", account.get("username") or "",
                        crypto.decrypt(account.get("secretEnc") or "")), timeout=90)
                except Exception as exc:  # one failing source must never stop the scan
                    cf_result = {"ok": False, "facts": [], "error": f"Cloudflare: {type(exc).__name__}"}
                if cf_result["ok"]:
                    await _label_providers(cf_result["facts"])
                    db.replace_exposure_facts("cloudflare", account["id"], cf_result["facts"])
                    log(f"Cloudflare ({account['label']}): {len(cf_result['facts'])} Eintrag/Einträge gelesen")
                    warnings += [f"Cloudflare ({account['label']}): {w}" for w in cf_result.get("warnings") or []]
                else:
                    db.mark_exposure_facts_stale("cloudflare", account["id"])
                    warnings.append(f"Cloudflare ({account['label']}): {cf_result['error']}")
                    if account.get("systemId"):
                        db.add_device_error_event(account["systemId"], "error", cf_result["error"])
            db.prune_exposure_facts("cloudflare", [a["id"] for a in cf_accounts])
        else:
            db.delete_exposure_facts(source="cloudflare")

        if settings.get("scanEnablePublicDns", False):
            hosts = public_dns.hostnames(db.list_exposure_facts())
            if hosts:
                progress("Öffentliches DNS", 88, "Löse öffentliche Hostnamen auf")
                try:
                    dns_result = await asyncio.wait_for(public_dns.resolve(hosts), timeout=120)
                except Exception as exc:  # one failing source must never stop the scan
                    dns_result = {"ok": False, "facts": [], "skipped": 0, "error": f"Öffentliches DNS: {type(exc).__name__}"}
                if dns_result["ok"]:
                    db.replace_exposure_facts("public_dns", "public", dns_result["facts"])
                    log(f"Öffentliches DNS: {len(dns_result['facts'])} Hostname(n) aufgelöst"
                        + (f", {dns_result['skipped']} nicht abgefragt" if dns_result["skipped"] else ""))
                else:
                    db.mark_exposure_facts_stale("public_dns", "public")
                    warnings.append(dns_result["error"])
            else:
                db.delete_exposure_facts(source="public_dns")
        else:
            db.delete_exposure_facts(source="public_dns")

        if settings.get("scanUseLlm", True):
            progress("Geräte einordnen (KI)", 89, "KI-Einordnung unbekannter Geräte")
            findings, classify_warnings = await _classify_new_findings(findings, settings, log)
            warnings += classify_warnings

        _make_names_unique(findings)

        progress("Inventar aktualisieren", 92, None)
        seen_ids: set[str] = set()
        for finding in findings:
            system, was_created = db.upsert_discovered_system(finding)
            seen_ids.add(system["id"])
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        db.mark_systems_offline(seen_ids)
        log(f"Inventar: {created} neu, {updated} aktualisiert")

        host_ip = result.get("hostIp", "")
        if host_ip:
            linked = db.link_containers_to_host(host_ip)
            if linked:
                log(f"{linked} Container dem Host {host_ip} zugeordnet")

        linked_omada = _link_omada_topology()
        if linked_omada:
            log(f"{linked_omada} Omada-Gerät(e)/Client(s) im Netzplan mit ihrem Uplink verknüpft")

        linked_unifi = _link_unifi_topology()
        if linked_unifi:
            log(f"{linked_unifi} UniFi-Gerät(e)/Client(s) im Netzplan mit ihrem Uplink verknüpft")

        for account, unifi_result in unifi_results:
            synced = db.sync_network_resources(
                account["id"], unifi_result["resources"], unifi_result["completeScopes"],
            )
            log(f"UniFi ({account['label']}): {len(synced)} Netze, WLANs und WANs aktualisiert")
        # WAN status comes from the classic API but belongs on the WAN rows of the integration API
        # (same account), so it is attached only after those rows are synced.
        for account_id, wans in classic_wans:
            # UniFi's geo address can lag behind a reconnect; the upstream router knows the real one.
            db.set_wan_status(account_id, [{**w, "ip": fritz_ip} if fritz_ip and w.get("publicOrigin") == "geo" else w
                                           for w in wans])

        # Anything critical is worth watching continuously -- that is what "critical" means. Done
        # here rather than in the UI so it also covers devices a scan just promoted.
        newly_monitored = 0
        for system in db.list_systems():
            if system["importance"] == "critical" and not system["monitored"] and system["ip"]:
                db.update_system(system["id"], {"monitored": 1})
                newly_monitored += 1
        if newly_monitored:
            log(f"{newly_monitored} wichtige Geräte zur Dauerüberwachung hinzugefügt")

        probed = 0
        if settings.get("scanUseCredentials", True):
            progress("Geräte mit hinterlegtem Zugang abfragen", 94, None)
            probed, probe_warnings, learned_arp, printer_supplies = await _probe_with_credentials(log)
            warnings += probe_warnings
            if learned_arp:
                await _learn_devices_from_arp(learned_arp, log)
            if printer_supplies:
                _apply_printer_supplies(printer_supplies, log)
        else:
            log("Auslesen per Zugangsdaten ist in den Einstellungen abgeschaltet")

        progress("Dokumentation schreiben", 96, None)
        try:
            pages = await docs.generate(db.get_settings(), use_llm=settings.get("scanUseLlm", True), log=log)
            log(f"{len(pages)} Kapitel geschrieben")
        except Exception as exc:  # noqa: BLE001 -- the inventory is already saved and is the
            # valuable part; a failed documentation pass must not discard it.
            warnings.append(f"Dokumentation konnte nicht vollständig erzeugt werden: {exc}")

        summary = {
            "devicesFound": len(findings),
            "created": created,
            "updated": updated,
            "probed": probed,
            "routedTargets": result.get("routedTargets") or [],
            "subnets": result["subnets"],
            "gateway": result["gateway"],
            "dnsServers": result["dnsServers"],
            "counts": result["counts"],
            "warnings": warnings,
        }
        db.finish_scan(scan_id, "completed", summary)
        progress("Fertig", 100, "Scan abgeschlossen")
    except Exception as exc:  # noqa: BLE001 -- background task; the failure has to land in the row
        db.update_scan(scan_id, log_line=f"FEHLER: {exc}\n{traceback.format_exc(limit=3)}")
        db.finish_scan(scan_id, "failed", {"error": str(exc), "warnings": warnings})


# ---------------------------------------------------------------------------------------------
# Scheduler -- an optional, opt-in timer around run_full_scan (which is also how config backups
# happen, see probe_auth.persist_config_backups above). Same start/stop/loop shape as monitor.py's
# Monitor: settings are re-read every tick, so flipping "scanAutoEnabled" or changing the interval
# in SettingsPage takes effect within one poll, not only after a restart or the previous
# (possibly day-long) interval elapses.
# ---------------------------------------------------------------------------------------------

# How often the loop wakes to check whether a scan is *due* -- not the scan interval itself.
_SCHEDULER_POLL_SECONDS = 300


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.last_error: str = ""

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._maybe_run()
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- the loop has to outlive any single failure
                self.last_error = str(exc)
            await asyncio.sleep(_SCHEDULER_POLL_SECONDS)

    async def _maybe_run(self) -> None:
        settings = db.get_settings()
        if not settings.get("scanAutoEnabled", False):
            return
        if db.running_scan() is not None:
            return  # a manual (or already-running automatic) scan takes priority -- never queue a second one
        interval_hours = max(1, min(24 * 30, int(settings.get("scanAutoIntervalHours") or 24)))
        latest = db.latest_scan()
        if latest is not None:
            started = datetime.strptime(latest["startedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - started < timedelta(hours=interval_hours):
                return  # last scan (manual or automatic) is still recent enough
        scan_id = db.create_scan("automatisch (Zeitplan)")
        await run_full_scan(scan_id)

    def status(self) -> dict:
        return {"running": self._task is not None and not self._task.done(), "lastError": self.last_error}


scheduler = Scheduler()
