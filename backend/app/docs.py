"""Turns the inventory into topic-sorted Markdown that a non-technical household member can read.

Chapters are organised by *what something is for* ("Wärme, Klima und Energie") rather than by
protocol or address range, because that is how someone looks for it when the heating app stops
working.

Each page is assembled in two layers. The factual layer -- device tables, ports, accounts, the
emergency checklist -- is generated deterministically from the database and is always correct
without any LLM involved. The narrative intro on top is optional and LLM-written; if no API key is
configured, or the call fails, a hand-written fallback is used and the page is still complete.
That split is deliberate: documentation that silently degrades to nothing when a token expires
would be worse than useless.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from . import db, discovery, exposure, firewall_eval, llm_providers, probe_auth, prompts

KIND_LABELS = {
    "router": "Router", "network": "Netzwerk-Gerät", "server": "Server", "nas": "Netzwerkspeicher",
    "container": "Container", "vm": "Virtuelle Maschine", "pc": "Computer", "mobile": "Mobilgerät",
    "printer": "Drucker", "camera": "Kamera", "smarthome": "Smart Home", "climate": "Klima",
    "heating": "Heizung", "energy": "Energie", "media": "Medien", "iot": "IoT-Gerät", "other": "Sonstiges",
}

STATUS_LABELS = {"online": "erreichbar", "offline": "nicht erreichbar", "unknown": "unbekannt"}
IMPORTANCE_LABELS = {"critical": "kritisch", "normal": "normal", "low": "gering"}


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    kinds: tuple[str, ...]
    intro_hint: str
    fallback: str
    sort_order: int
    include_accounts: bool = False
    extra_sections: tuple[str, ...] = field(default=())


TOPICS: tuple[Topic, ...] = (
    Topic(
        "ueberblick", "Überblick: So hängt alles zusammen", (),
        "Ein Überblick über das gesamte Heimnetz: was es gibt, wie die Teile zusammenhängen und wo man anfängt zu suchen.",
        "Diese Seite fasst zusammen, woraus das Heimnetz besteht. Die Kapitel danach gehen ins Detail.",
        0,
    ),
    Topic(
        "internet-und-router", "Internet und Router", ("router",),
        "Der Router und die Verbindung ins Internet.",
        "Der Router ist die Schaltzentrale des Heimnetzes: Er verbindet alle Geräte im Haus miteinander "
        "und stellt die Verbindung ins Internet her. Fällt er aus, funktioniert nichts mehr -- weder "
        "Internet noch das Netz im Haus selbst.",
        1,
    ),
    Topic(
        "netzwerk", "Netzwerk: Switche, WLAN und Verkabelung", ("network",),
        "Switche, Access Points und WLAN-Verstärker, die das Netz im Haus verteilen.",
        "Diese Geräte verteilen das Netzwerk im Haus weiter: Switche verbinden Geräte per Kabel, "
        "Access Points und Repeater bringen das WLAN in entferntere Räume.",
        2,
    ),
    Topic(
        "server-und-speicher", "Server und Netzwerkspeicher", ("server", "nas"),
        "Dauerhaft laufende Rechner und Netzwerkspeicher.",
        "Hier laufen die Dienste, die immer verfügbar sein sollen, und hier liegen zentrale Daten. "
        "Diese Geräte laufen typischerweise rund um die Uhr.",
        3,
    ),
    Topic(
        "container-und-vms", "Container und virtuelle Maschinen", ("container", "vm"),
        "Die einzelnen Anwendungen, die auf dem Server in Containern laufen.",
        "Container sind voneinander abgeschottete kleine Anwendungspakete auf einem Server. Jeder "
        "enthält genau eine Anwendung mit allem, was sie zum Laufen braucht. Startet ein Container "
        "nicht mehr, ist meist nur diese eine Anwendung betroffen -- der Rest läuft weiter.",
        4,
    ),
    Topic(
        "computer-und-mobilgeraete", "Computer und Mobilgeräte", ("pc", "mobile"),
        "Arbeitsplatzrechner, Notebooks, Tablets und Telefone.",
        "Die persönlichen Geräte im Haushalt. Diese sind nicht immer eingeschaltet -- dass eines "
        "gerade nicht erreichbar ist, ist hier also normal. Telefone wechseln außerdem regelmäßig "
        "ihre Netzwerkkennung, sie können deshalb mehrfach auftauchen.",
        5,
    ),
    Topic(
        "smart-home", "Smart Home und Automation", ("smarthome", "iot"),
        "Die Smart-Home-Zentrale und die daran angebundenen Geräte.",
        "Smart-Home-Geräte werden meist über eine Zentrale gesteuert. Reagiert ein einzelnes Gerät "
        "nicht mehr, lohnt der erste Blick auf diese Zentrale -- oft ist nicht das Gerät das Problem, "
        "sondern die Verbindung dorthin.",
        6,
    ),
    Topic(
        "klima-heizung-energie", "Wärme, Klima und Energie", ("heating", "climate", "energy"),
        "Heizung, Klimatisierung, Photovoltaik und alles rund um Energie.",
        "Heizungs- und Energietechnik hängt oft am Netzwerk, um Daten zu liefern oder fernsteuerbar zu "
        "sein. Wichtig: Die Heizung selbst funktioniert in aller Regel weiter, auch wenn ihre "
        "Netzwerkverbindung gestört ist -- dann fehlt nur die Anzeige oder die Fernsteuerung.",
        7,
    ),
    Topic(
        "drucker-medien-kameras", "Drucker, Medien und Kameras", ("printer", "media", "camera"),
        "Drucker, Streaming-Geräte, Lautsprecher und Kameras.",
        "Geräte, die im Alltag sichtbar genutzt werden. Drucker und Streaming-Geräte melden sich meist "
        "selbst im Netzwerk an, damit andere Geräte sie automatisch finden.",
        8,
    ),
    Topic(
        "sonstige-geraete", "Weitere Geräte", ("other",),
        "Geräte, die sich noch nicht eindeutig zuordnen ließen.",
        "Diese Geräte antworten im Netzwerk, ließen sich aber noch nicht sicher einordnen. Wer weiß, "
        "worum es sich handelt, kann sie in der Geräteübersicht benennen -- danach bleibt die Angabe "
        "erhalten und wird bei künftigen Scans nicht überschrieben.",
        9,
    ),
    Topic(
        "erreichbarkeit", "Erreichbarkeit von außen", (),
        "Welche Dienste aus dem Internet und welche intern per TLS erreichbar sind, und auf welchem Weg.",
        "Hier steht, welche Dienste von außerhalb des Hauses erreichbar sind und über welchen Weg, "
        "und welche Dienste im Heimnetz verschlüsselt über einen Reverse Proxy laufen.",
        10, extra_sections=("exposure",),
    ),
    Topic(
        "zugaenge-und-konten", "Zugänge und Konten", (),
        "Wo welche Zugangsdaten hinterlegt sind.",
        "Hier ist vermerkt, für welche Geräte und Dienste Zugangsdaten in HomeAtlas hinterlegt sind. "
        "Die Passwörter selbst stehen bewusst nicht in dieser Dokumentation -- sie sind verschlüsselt "
        "gespeichert und nur in der Geräteansicht sichtbar.",
        11, include_accounts=True,
    ),
    Topic(
        "notfall", "Wenn etwas nicht funktioniert", (),
        "Eine Checkliste für den Störungsfall.",
        "", 12, extra_sections=("emergency",),
    ),
    Topic(
        "wer-darf-mit-wem", "Wer darf mit wem sprechen", (),
        "Welche Netze und Geräte laut Firewall miteinander sprechen dürfen.",
        "Hier steht, welche Netze (Zonen) laut Firewall miteinander sprechen dürfen und wo es Ausnahmen gibt. "
        "Die Regeln werden nur gelesen, nie verändert.",
        13, extra_sections=("firewall",),
    ),
)


# What a device of this kind is *for*, in one sentence a non-technical reader understands. Used
# only when nothing better is stored, so a real description or an LLM-written purpose always wins.
_KIND_PURPOSE = {
    "router": "Verbindet das Haus mit dem Internet und verteilt das Netz an alle Geräte.",
    "network": "Verteilt das Netzwerk im Haus weiter — per Kabel oder als WLAN.",
    "server": "Ein dauerhaft laufender Rechner, auf dem Dienste für den Haushalt bereitstehen.",
    "nas": "Zentraler Netzwerkspeicher: hier liegen gemeinsam genutzte Dateien und Sicherungen.",
    "container": "Eine einzelne Anwendung, abgeschottet auf einem Server ausgeführt.",
    "vm": "Ein vollständiger virtueller Rechner, der auf einem größeren Server läuft.",
    "pc": "Ein persönlicher Rechner im Haushalt.",
    "mobile": "Ein Telefon oder Tablet im WLAN.",
    "printer": "Netzwerkdrucker, über den alle Geräte im Haus drucken können.",
    "camera": "Kamera, die ihr Bild über das Netzwerk bereitstellt.",
    "smarthome": "Teil der Smart-Home-Steuerung — schaltet, misst oder steuert etwas im Haus.",
    "climate": "Steuert oder misst Temperatur, Lüftung oder Luftqualität.",
    "heating": "Gehört zur Heizung oder Wärmepumpe.",
    "energy": "Gehört zur Energieversorgung — Photovoltaik, Ladestation oder Stromzähler.",
    "media": "Gibt Musik oder Video wieder oder streamt es ins Haus.",
    "iot": "Kleines vernetztes Gerät mit einer speziellen Aufgabe.",
    "other": "",
}


def describe_device(system: dict) -> str:
    """Best available "what is this for" sentence.

    Falls back through: hand-written description → purpose → what the kind implies, enriched by the
    most telling open service. Without the fallback most entries in "Die Geräte im Einzelnen" would
    show nothing at all, which is precisely the section someone reads to find out what a device is.
    """
    description = (system.get("descriptionMd") or "").strip()
    if description:
        return description
    purpose = (system.get("purpose") or "").strip()
    if purpose and not purpose.startswith("Gerät "):
        return purpose

    base = _KIND_PURPOSE.get(system.get("kind", ""), "")
    services = system.get("services") or []
    hint = ""
    if services:
        # Name the single most identifying service rather than listing ports.
        primary = next(
            (s for s in services if s["port"] in (8123, 32400, 8096, 9100, 631, 445, 5001, 8006, 1883, 554)),
            services[0],
        )
        hint = f" Erreichbar ist unter anderem {primary['service']} — {primary['explanation'][0].lower()}{primary['explanation'][1:]}."

    docker = (system.get("extra") or {}).get("docker") or {}
    if docker.get("image"):
        hint = f" Läuft als Container aus dem Image `{docker['image']}`." + hint

    if not base and not hint:
        return ""
    return (base + hint).strip()


def _fmt_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return value


def scrub_config_exports(markdown: str) -> str:
    """Removes config-export facts from already rendered Markdown -- for pages and page versions
    generated before exports were kept out of extra.probe. Matches both shapes the renderer below
    produces: a multi-line value in an indented code block, and a single-line value inline."""
    for label in probe_auth.CONFIG_BACKUP_LABELS:
        bullet = re.escape(f"- **{_escape(label)}:**")
        markdown = re.sub(bullet + r"\n\n  ```\n.*?\n  ```\n", "", markdown, flags=re.S)
        markdown = re.sub(bullet + r" [^\n]*\n?", "", markdown)
    return markdown


def _escape(text: str) -> str:
    """Markdown tables break on a raw pipe in a device name; devices really are named things like
    'Drucker | Büro'."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _device_table(systems: list[dict]) -> str:
    if not systems:
        return "_In dieser Kategorie ist bisher nichts dokumentiert._\n"
    lines = [
        "| Gerät | Adresse im Netz | Art | Zustand | Standort |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in systems:
        address = s["ip"] or "-"
        if s["hostname"]:
            address = f"{address} ({_escape(s['hostname'].split('.')[0])})"
        lines.append(
            f"| **{_escape(s['name'])}** | {_escape(address)} | {KIND_LABELS.get(s['kind'], s['kind'])} "
            f"| {STATUS_LABELS.get(s['status'], s['status'])} | {_escape(s['location']) or '-'} |"
        )
    return "\n".join(lines) + "\n"


def _compose_project(system: dict) -> str:
    return (((system.get("extra") or {}).get("docker") or {}).get("composeProject") or "").strip()


def _grouped_device_details(systems: list[dict], by_id: dict[str, dict],
                            children_by_parent: dict[str, list[dict]]) -> str:
    """Container chapter: one heading per compose stack, devices one level below. Without any
    compose project the output is identical to the flat listing."""
    projects = sorted({p for p in map(_compose_project, systems) if p}, key=str.lower)
    if not projects:
        return _device_details(systems, by_id, children_by_parent)
    parts = []
    for project in projects:
        members = sorted((s for s in systems if _compose_project(s) == project), key=lambda s: s["name"].lower())
        parts.append(f"### Stack: {_escape(project)}\n")
        parts.append(_device_details(members, by_id, children_by_parent, level=4))
    rest = [s for s in systems if not _compose_project(s)]
    if rest:
        parts.append("### Ohne Compose-Projekt\n")
        parts.append(_device_details(rest, by_id, children_by_parent, level=4))
    return "\n".join(parts)


def _device_details(systems: list[dict], by_id: dict[str, dict], children_by_parent: dict[str, list[dict]],
                    level: int = 3) -> str:
    parts: list[str] = []
    for s in systems:
        parts.append(f"{'#' * level} {s['name']}\n")
        description = describe_device(s)
        if description:
            parts.append(f"{description}\n")

        facts = []
        if s["ip"]:
            facts.append(f"- **Adresse im Netzwerk:** {s['ip']}")
        if s["mac"]:
            facts.append(f"- **Geräte-Kennung (MAC):** `{s['mac']}`")
        if s["vendor"]:
            facts.append(f"- **Hersteller:** {_escape(s['vendor'])}")
        if s["model"]:
            facts.append(f"- **Modell:** {_escape(s['model'])}")
        if s["location"]:
            facts.append(f"- **Standort:** {_escape(s['location'])}")
        if s["importance"] != "normal":
            facts.append(f"- **Bedeutung:** {IMPORTANCE_LABELS.get(s['importance'], s['importance'])}")
        parent = by_id.get(s.get("parentId") or "")
        if parent:
            facts.append(f"- **Läuft auf:** {_escape(parent['name'])}")
        if s["url"]:
            facts.append(f"- **Weboberfläche:** [{s['url']}]({s['url']})")
        if s.get("docUrl"):
            facts.append(f"- **Hersteller-Dokumentation:** [{s['docUrl']}]({s['docUrl']})")
        if s.get("docLink"):
            facts.append(f"- **Eigene Dokumentation:** [{s['docLink']}]({s['docLink']})")
        facts.append(f"- **Zuletzt gesehen:** {_fmt_date(s['lastSeen'])}")
        parts.append("\n".join(facts) + "\n")

        probe = (s.get("extra") or {}).get("probe") or {}
        # Config exports never belong in the docs (members and the LLM read them); they are already
        # kept out of extra.probe, this is the second line of defence for rows written before that.
        readings = [
            (fact["label"], fact["value"])
            for result in probe.values() if result.get("ok")
            for key, fact in (result.get("facts") or {}).items()
            if key not in probe_auth.CONFIG_BACKUP_KEYS
        ]
        if readings:
            parts.append("**Direkt vom Gerät ausgelesen**\n")
            for label, value in readings[:14]:
                # Multi-line command output (disks, services) belongs in a code block; a single
                # value reads better inline.
                if "\n" in value:
                    parts.append(f"- **{_escape(label)}:**\n\n  ```\n  " + value.replace("\n", "\n  ") + "\n  ```\n")
                else:
                    parts.append(f"- **{_escape(label)}:** {_escape(value)}")
            parts.append("")

        docker = (s.get("extra") or {}).get("docker") or {}
        if docker:
            docker_facts = [f"- **Image:** `{docker.get('image', '')}`"]
            if docker.get("composeProject"):
                docker_facts.append(f"- **Compose-Projekt:** `{docker['composeProject']}`")
            if docker.get("portMappings"):
                docker_facts.append(f"- **Port-Zuordnungen (Docker):** `{', '.join(docker['portMappings'])}`")
            if docker.get("volumes"):
                docker_facts.append(f"- **Datenablagen (Volumes):** `{', '.join(docker['volumes'][:6])}`")
            parts.append("\n".join(docker_facts) + "\n")

        proxmox = (s.get("extra") or {}).get("proxmox") or {}
        if proxmox:
            proxmox_facts = [f"- **Proxmox-Node:** {_escape(str(proxmox.get('node', '')))}"]
            if proxmox.get("vmid"):
                proxmox_facts.append(f"- **VM-/Container-ID:** {proxmox['vmid']}")
            if proxmox.get("cpuCores"):
                proxmox_facts.append(f"- **CPU-Kerne:** {proxmox['cpuCores']}")
            if proxmox.get("memoryMb"):
                proxmox_facts.append(f"- **Arbeitsspeicher:** {proxmox['memoryMb']} MB")
            parts.append("\n".join(proxmox_facts) + "\n")

        children = sorted(children_by_parent.get(s["id"], []), key=lambda c: c["name"])
        if children:
            parts.append("**Läuft auf diesem Gerät**\n")
            child_rows = ["| Name | Art | Zustand | Funktion | Weboberfläche |", "| --- | --- | --- | --- | --- |"]
            for c in children:
                link = f"[öffnen]({c['url']})" if c.get("url") else "-"
                child_rows.append(
                    f"| **{_escape(c['name'])}** | {KIND_LABELS.get(c['kind'], c['kind'])} "
                    f"| {STATUS_LABELS.get(c['status'], c['status'])} "
                    f"| {_escape(describe_device(c))[:140] or '-'} | {link} |"
                )
            parts.append("\n".join(child_rows) + "\n")

        services = s.get("services") or []
        if services:
            parts.append("**Erreichbare Dienste**\n")
            parts.append("| Port | Dienst | Bedeutung |\n| --- | --- | --- |")
            parts.append("\n".join(
                f"| {svc['port']} | {_escape(svc['service'])} | {_escape(svc['explanation'])} |"
                for svc in services[:15]
            ) + "\n")

        if any("poe" in tag.lower() for tag in (s.get("tags") or [])):
            parts.append(
                "> ⚡ **Benötigt PoE:** Dieses Gerät bezieht seinen Strom über das Netzwerkkabel "
                "und funktioniert nur an einem PoE-fähigen Switch oder mit einem PoE-Injector.\n"
            )

        if s["notes"]:
            parts.append(f"> **Notiz:** {_escape(s['notes'])}\n")
    return "\n".join(parts)


def _accounts_section() -> str:
    accounts = db.list_accounts()
    if not accounts:
        return ("_Es sind bisher keine Zugänge hinterlegt._ Zugänge lassen sich in der Geräteansicht "
                "oder über die Ersteinrichtung ergänzen.\n")
    systems = {s["id"]: s["name"] for s in db.list_systems()}
    lines = [
        "| Zugang | Art | Benutzername | Gehört zu | Adresse | Passwort hinterlegt |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    categories = {"login": "Anmeldung", "apikey": "API-Schlüssel", "wifi": "WLAN",
                  "contract": "Vertrag/Kundenkonto", "other": "Sonstiges"}
    for a in accounts:
        url = f"[{_escape(a['url'])}]({a['url']})" if a["url"] else "-"
        lines.append(
            f"| **{_escape(a['label'])}** | {categories.get(a['category'], a['category'])} "
            f"| {_escape(a['username']) or '-'} | {_escape(systems.get(a['systemId'] or '', '-'))} "
            f"| {url} | {'ja' if a['secretEnc'] else 'nein'} |"
        )
    return "\n".join(lines) + (
        "\n\n> Die Passwörter selbst stehen absichtlich nicht in der Dokumentation. Sie sind "
        "verschlüsselt gespeichert und lassen sich in HomeAtlas beim jeweiligen Zugang anzeigen.\n"
    )


def _network_resources_section() -> str:
    """Render controller data separately from discovered devices; local notes remain visible."""
    resources = db.list_network_resources(active_only=True)
    if not resources:
        return "_Noch keine VLAN-, WLAN- oder WAN-Daten vom Controller erfasst._\n"
    sections: list[str] = []
    tables = (
        ("network", "### VLANs und Netze", ("VLAN", "Netzwerk"),
         lambda facts: (str(facts.get("vlanId", "-")), facts.get("cidr", "-"))),
        ("wifi", "### WLANs", ("Sicherheit",),
         lambda facts: (facts.get("security", "-"),)),
        ("wan", "### Internet-Anschlüsse", ("Typ", "Adresse"),
         lambda facts: (facts.get("type", "-"), facts.get("ip", "-"))),
    )
    for kind, title, columns, values in tables:
        items = [resource for resource in resources if resource["kind"] == kind]
        if kind == "wan" and any((r.get("facts") or {}).get("ip") for r in items):
            # the integration API lists WANs without address; the classic API adds them with one
            items = [r for r in items if (r.get("facts") or {}).get("ip")]
        if not items:
            continue
        headers = ("Name", "Standort", *columns, "Notiz")
        lines = [title, "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        for resource in items:
            facts = resource.get("facts") or {}
            row = (resource["name"], resource["siteName"], *values(facts), resource.get("manualMd") or "-")
            lines.append("| " + " | ".join(_escape(str(value)) for value in row) + " |")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


_EXPOSURE_EMPTY = ("_Noch keine Erreichbarkeits-Daten erfasst. Sobald eine Quelle (Reverse Proxy, Tunnel, "
                   "Router, DynDNS) eingerichtet ist, erscheinen die Wege hier._\n")


def _md(value: object, limit: int = 120) -> str:
    """Hostnames and names come from third-party configs: escape table syntax and cap the length."""
    text = _escape(str(value or ""))
    text = text.replace("`", "'").replace("<", "‹").replace(">", "›")
    return text[:limit] or "-"


def _sys_names(systems: list[dict]) -> str:
    return ", ".join(_md(s["name"]) for s in systems) or "nicht im Inventar"


def _firewall_label(result: dict | None) -> str:
    """Verdict of a chain step, with the reason unless it is simply allowed."""
    result = result or {}
    verdict = _md(result.get("verdict") or "unklar")
    reason = result.get("reason") if verdict != "erlaubt" else ""
    return f"{verdict}: {_md(reason, 140)}" if reason else verdict


def _exposure_section() -> str:
    """Chapter body for reachability; facts only, no secrets ever reach this (ADR-0014)."""
    wan = next((r.get("facts") or {} for r in db.list_network_resources(kind="wan", active_only=True)
                if (r.get("facts") or {}).get("ip")), None)
    data = exposure.build_chains(db.list_exposure_facts(), db.list_systems(), wan)
    if not data["hasData"]:
        return _EXPOSURE_EMPTY
    firewall_eval.annotate_chains(data["chains"], db.list_firewall_facts(), db.list_systems(),
                                  db.list_network_resources(kind="network", active_only=True))
    out: list[str] = []
    if data["chains"]:
        out.append("### Von außen erreichbar\n")
        for chain in data["chains"]:
            out.append(f"**{_md(chain['host'])}**" + (" (über Cloudflare)" if chain["cloudflare"] else ""))
            for path in chain["paths"]:
                steps = " → ".join(
                    f"{_md(s['label'])} ({_sys_names(s['systems'])}) [Firewall: {_firewall_label(s.get('firewall'))}]"
                    for s in path["steps"]) or "-"
                guard = ", Client-Zertifikat (mTLS) nötig" if path["mtls"] else ""
                out.append(f"- {path['sourceLabel']} [{path['status']}{guard}]: Internet → {steps}")
            out.extend(f"- Hinweis: {_md(h, 300)}" for h in chain["hints"])
            out.append("")
    if data["direct"]:
        out += ["### Direkt über den Internetanschluss erreichbar\n",
                "| Hostname | Zeigt auf | Status | Weiterleitung |", "| --- | --- | --- | --- |"]
        for row in data["direct"]:
            ways = ", ".join(f"{p['wanPort']} → {p['destIp']}:{p['destPort']} ({_sys_names(p['systems'])})"
                             for p in row["forwards"])
            guard = ", Client-Zertifikat (mTLS) nötig" if row["mtls"] else ""
            out.append(f"| {_md(row['host'])} | {_md(row['target'])} | {row['status']}{guard} | {_md(ways, 300)} |")
        out.append("")
    if data["external"]:
        out.append("### Extern gehostet\n")
        out += ["| Hostname | Ziel | Anbieter |", "| --- | --- | --- |"]
        out += [f"| {_md(e['host'])} | {_md(e['target'])} | {_md(e['provider'])} |" for e in data["external"]]
        out.append("")
    if data["internal"]:
        out += ["### Intern per TLS erreichbare Dienste\n", "| Hostname | Ziel | Zertifikat | Schutz |",
                "| --- | --- | --- | --- |"]
        # A TLS router without its own resolver uses Traefik's default certificate store.
        out += [f"| {_md(r['host'])} | {_md(r['target'])} ({_sys_names(r['systems'])}) | "
                f"{_md(r['resolver'] or ('TLS, Standardzertifikat' if r.get('tls') else ''))} | "
                f"{_md(', '.join(r['middlewares']))} |" for r in data["internal"]]
        out.append("")
    if data["ddns"]:
        out += ["### DynDNS\n", "| System | Anbieter | Hostname | IPv4/IPv6 | Zeigt auf WAN-IP |",
                "| --- | --- | --- | --- | --- |"]
        for d in data["ddns"]:
            fam = "/".join(n for n, on in (("IPv4", d["ipv4"]), ("IPv6", d["ipv6"])) if on) or "-"
            for h in d["hosts"] or [{"host": "", "resolvesToWan": None}]:
                ok = {True: "ja", False: "nein", None: "unbekannt"}[h["resolvesToWan"]]
                out.append(f"| {_sys_names(d['system'])} | {_md(d['provider'])} | {_md(h['host'])} | {fam} | {ok} |")
        out.append("")
    if data["portforwards"]:
        out += ["### Portweiterleitungen\n", "| Protokoll | Port außen | Ziel | System |", "| --- | --- | --- | --- |"]
        out += [f"| {_md(p['proto'])} | {_md(p['wanPort'])} | {_md(p['destIp'])}:{_md(p['destPort'])} | "
                f"{_sys_names(p['systems'])} |" for p in data["portforwards"]]
        out.append("")
    elif data["portforwardsChecked"]:
        out += ["### Portweiterleitungen\n", "_Auf dem Router sind keine Portweiterleitungen eingerichtet._", ""]
    settings = db.get_settings()
    if not (settings.get("scanEnableCloudflare") and settings.get("scanEnablePublicDns")):
        out += ["_Cloudflare/öffentliches DNS aus – Status unklar. In den Einstellungen aktivieren._", ""]
    if data["hints"]:
        out.append("### Hinweise\n")
        out += [f"- {_md(h, 300)}" for h in data["hints"]]
    return "\n".join(out) + "\n"


_FIREWALL_EMPTY = ("_Noch keine Firewall-Daten erfasst. Sobald die UniFi-Firewall oder die nftables-Regeln "
                   "von Hosts gelesen werden (Einstellungen und Zugänge), erscheint hier, wer mit wem sprechen darf._\n")


def _firewall_section() -> str:
    """Chapter body for firewall rules: zone matrix, exceptions, important systems, host firewalls, hints.
    Built from stored facts only (ADR-0017); rule names are third-party text and go through `_md`."""
    facts = db.list_firewall_facts()
    if not facts:
        return _FIREWALL_EMPTY
    systems = db.list_systems()
    names = {s["id"]: s["name"] for s in systems}
    data = firewall_eval.zone_matrix(facts)
    zones = data["zones"]
    out: list[str] = []
    if zones:
        title = lambda z: _md(z.get("name"), 40)  # noqa: E731
        out += ["### Zonenmatrix (von Zeile nach Spalte)\n", "| Von \\ nach | " + " | ".join(title(z) for z in zones) + " |",
                "| --- |" + " --- |" * len(zones)]
        for a in zones:
            row = []
            for b in zones:
                cell = data["cells"].get(a["id"], {}).get(b["id"])
                row.append("-" if cell is None else f"teilweise ({len(cell['exceptions'])})" if cell["state"] == "teilweise"
                           else cell["state"])
            out.append(f"| {title(a)} | " + " | ".join(row) + " |")
        if data["extraZones"]:
            out.append(f"\n_und {data['extraZones']} weitere Zonen_")
        out.append("")
        lines: list[str] = []
        for a in zones:
            for b in zones:
                cell = data["cells"].get(a["id"], {}).get(b["id"])
                if not cell or not cell["exceptions"]:
                    continue
                base = "gesperrt" if cell["default"] == "BLOCK" else "erlaubt"
                joiner = "außer" if cell["default"] == "BLOCK" else "aber gesperrt:"
                keep = cell["exceptions"][:data["maxExceptions"]]
                text = "; ".join(_md(e, 100) for e in keep)
                more = len(cell["exceptions"]) - len(keep)
                lines.append(f"- {title(a)} → {title(b)}: {base}, {joiner} {text}"
                             + (f" und {more} weitere" if more > 0 else ""))
        if lines:
            out += ["### Ausnahmen je Zonenpaar\n", *lines, ""]
        # important systems: which zones may talk to the zone they sit in
        important = []
        for system in (s for s in systems if s.get("importance") == "critical" and s.get("ip")):
            zone, _ = firewall_eval.zone_of(system["ip"], zones, db.list_network_resources(kind="network", active_only=True))
            if zone is None:
                continue
            states = [(title(a), data["cells"].get(a["id"], {}).get(zone["id"])) for a in zones if a["id"] != zone["id"]]
            reach = [f"{n} ({c['state']})" for n, c in states if c and c["state"] != "gesperrt"]
            important.append(f"- {_md(system['name'])} (Zone {title(zone)}): erreichbar aus "
                             + (", ".join(reach) if reach else "keiner anderen Zone"))
        if important:
            out += ["### Freigaben je wichtigem System\n", *important, ""]
    hosts = firewall_eval.host_firewalls(facts)
    if hosts:
        out.append("### Host-Firewalls\n")
        for host in hosts:
            out.append(f"**{_md(names.get(host['systemId'], 'unbekanntes System'))}**"
                       + (" (zuletzt nicht lesbar)" if host["stale"] else ""))
            out += [f"- {_md(c['kette'])} ({_md(c['hook'])}): Standard {_md(c['policy'])}, {c['rules']} Regeln"
                    + (f", davon {c['unsupported']} nicht sicher auswertbar" if c["unsupported"] else "")
                    for c in host["chains"][:10]]
            out.append("")
    hints = [f"- {firewall_eval.NOTE.split(' Regelnamen')[0]}"]
    if data["disabled"]:
        shown = ", ".join(_md(n, 60) for n in data["disabled"][:10])
        hints.append(f"- {len(data['disabled'])} deaktivierte Regel(n): {shown}")
    hints += [f"- Quelle „{_md(src)}“ war beim letzten Scan nicht lesbar – Stand kann veraltet sein." for src in data["stale"]]
    out += ["### Hinweise\n", *hints]
    return "\n".join(out) + "\n"


def _emergency_section(context: dict) -> str:
    router = context.get("router")
    router_line = (
        f"Der Router ist **{router['name']}** und ist im Netzwerk unter **{router['ip']}** erreichbar"
        + (f" -- Weboberfläche: [{router['url']}]({router['url']})" if router.get("url") else "")
        + "."
    ) if router else "Es ist noch kein Router dokumentiert -- ein Netzwerk-Scan trägt ihn automatisch ein."
    others = context.get("other_routers") or []
    if router and others:
        router_line += "\n\nWeitere Router: " + ", ".join(
            f"**{_escape(o['name'])}** ({o['ip'] or 'keine Adresse hinterlegt'})" for o in others
        )

    critical = context.get("critical") or []
    critical_lines = "\n".join(
        f"- **{_escape(s['name'])}** ({s['ip'] or 'keine Adresse hinterlegt'}) -- "
        f"{_escape(s['purpose'] or 'kein Zweck hinterlegt')}"
        for s in critical
    ) or "_Es ist bisher kein Gerät als kritisch markiert._"

    return f"""\
Diese Seite ist für den Fall gedacht, dass gerade etwas nicht funktioniert. Sie ist bewusst so
geschrieben, dass man ihr auch unter Zeitdruck folgen kann.

### Zuerst: Wie groß ist das Problem?

1. **Betrifft es nur ein Gerät?** Dann liegt es sehr wahrscheinlich an diesem Gerät. Aus- und
   wieder einschalten löst erstaunlich viel.
2. **Betrifft es alle Geräte, aber nur im Internet?** Also: das Heimnetz funktioniert (Drucker,
   Dateien, Smart Home gehen), nur Webseiten laden nicht. Dann liegt es am Internetzugang oder am
   Anbieter -- nicht an den Geräten im Haus.
3. **Geht gar nichts mehr?** Dann zuerst zum Router.

### Der Router

{router_line}

Am Router prüfen:
- Leuchten die Lampen wie sonst? Eine rote oder dunkle Internet-/DSL-Lampe heißt: die Leitung ins
  Haus ist gestört. Das kann man von innen nicht reparieren.
- Wenn unklar: Router 30 Sekunden vom Strom trennen, wieder anstecken und **zwei bis drei Minuten
  warten**. Er braucht diese Zeit, um die Internetverbindung neu aufzubauen.

### Diese Geräte sind besonders wichtig

Wenn eines davon ausfällt, merkt man das im ganzen Haus:

{critical_lines}

### Wenn es dabei bleibt

Der KI-Assistent in HomeAtlas kann live nachmessen: ob ein Gerät antwortet, ob die Namensauflösung
funktioniert, ob das Internet erreichbar ist. Beschreibe dort einfach in eigenen Worten, was nicht
geht -- er fragt gezielt nach und prüft selbst, statt dich raten zu lassen.
"""


def _overview_section(context: dict) -> str:
    counts = context.get("counts") or {}
    if not counts:
        return "_Noch keine Geräte dokumentiert. Starte einen Netzwerk-Scan, um zu beginnen._\n"
    lines = ["| Bereich | Anzahl Geräte |", "| --- | --- |"]
    lines += [f"| {KIND_LABELS.get(kind, kind)} | {count} |" for kind, count in sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    )]
    scan = context.get("last_scan")
    footer = (
        f"\nLetzter Netzwerk-Scan: **{_fmt_date(scan['startedAt'])}** "
        f"({', '.join(context.get('subnets') or []) or 'automatisch erkannter Bereich'}).\n"
        if scan else "\n_Es wurde noch kein Netzwerk-Scan durchgeführt._\n"
    )
    return "\n".join(lines) + "\n" + footer


async def _write_intro(topic: Topic, systems: list[dict], settings: dict) -> str:
    """LLM-written chapter intro. Returns the fallback on any failure -- a missing API key must not
    produce an empty page."""
    if not settings.get("scanUseLlm", True) or not llm_providers.is_configured(settings.get("llmProvider", ""), settings):
        return topic.fallback
    device_summary = "\n".join(
        f"- {s['name']} ({KIND_LABELS.get(s['kind'], s['kind'])})"
        + (f", {s['vendor']}" if s["vendor"] else "")
        + (f", Zweck: {s['purpose']}" if s["purpose"] else "")
        for s in systems[:25]
    ) or "(keine Geräte in dieser Kategorie)"
    try:
        result = await llm_providers.chat(
            settings.get("llmProvider", ""), settings, prompts.DOCS_SYSTEM,
            [{"role": "user", "content": (
                f"Kapitel: {topic.title}\nWorum es geht: {topic.intro_hint}\n\n"
                f"Diese Geräte sind in diesem Kapitel dokumentiert:\n{device_summary}\n\n"
                "Schreibe den einleitenden Text für dieses Kapitel."
            )}],
            purpose="ANALYSIS",
        )
        text = result.text.strip()
        return text or topic.fallback
    except Exception:  # noqa: BLE001 -- a chapter intro is never worth failing the whole run over
        return topic.fallback


def _systems_for(topic: Topic, all_systems: list[dict]) -> list[dict]:
    if not topic.kinds:
        return []
    return [s for s in all_systems if s["kind"] in topic.kinds]


def _pick_router(systems: list[dict]) -> tuple[dict | None, list[dict]]:
    """Primary router for the emergency page plus the remaining ones (inventory order).

    Order of preference: importance `critical` -> flagged default gateway (`extra.isGateway`) ->
    first in inventory order. Within a tier the first in inventory order wins, so the choice is
    deterministic. A second router (repeater, mesh node, modem behind the main router) must not
    be picked by accident of ordering."""
    routers = [s for s in systems if s["kind"] == "router"]
    if not routers:
        return None, []
    primary = (
        next((s for s in routers if s.get("importance") == "critical"), None)
        or next((s for s in routers if (s.get("extra") or {}).get("isGateway")), None)
        or routers[0]
    )
    return primary, [s for s in routers if s is not primary]


async def generate(settings: dict, use_llm: bool = True, log=None, only_slug: str | None = None) -> list[str]:
    """Regenerates every chapter, or only `only_slug` (chapter reset). Chapters that are skipped
    are neither rendered, nor sent to the LLM, nor versioned. Returns the slugs written."""
    all_systems = db.list_systems()
    by_id = {s["id"]: s for s in all_systems}
    children_by_parent: dict[str, list[dict]] = {}
    for s in all_systems:
        parent_id = s.get("parentId")
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(s)
    router, other_routers = _pick_router(all_systems)
    context = {
        "counts": {k: sum(1 for s in all_systems if s["kind"] == k) for k in {s["kind"] for s in all_systems}},
        "router": router,
        "other_routers": other_routers,
        "critical": [s for s in all_systems if s["importance"] == "critical"],
        "last_scan": db.latest_scan(),
        "subnets": discovery.effective_subnets(settings, db.list_network_resources(kind="network", active_only=True)),
    }

    written: list[str] = []
    for topic in TOPICS:
        if only_slug and topic.slug != only_slug:
            continue
        systems = _systems_for(topic, all_systems)
        sections: list[str] = []

        if "exposure" in topic.extra_sections:
            sections.append(topic.fallback + "\n")
            sections.append(_exposure_section())
            body = "\n".join(sections)
            intro = topic.intro_hint
        elif "firewall" in topic.extra_sections:
            sections.append(topic.fallback + "\n")
            sections.append(_firewall_section())
            body = "\n".join(sections)
            intro = topic.intro_hint
        elif "emergency" in topic.extra_sections:
            body = _emergency_section(context)
            intro = topic.intro_hint
        else:
            intro_text = (
                await _write_intro(topic, systems, settings)
                if use_llm and topic.kinds and systems else topic.fallback
            )
            sections.append(intro_text)
            if topic.slug == "ueberblick":
                sections.append("\n## Was es im Heimnetz gibt\n")
                sections.append(_overview_section(context))
            if topic.include_accounts:
                sections.append("\n## Hinterlegte Zugänge\n")
                sections.append(_accounts_section())
            if topic.slug == "netzwerk":
                sections.append("\n## Vom Controller erfasste Netze\n")
                sections.append(_network_resources_section())
            if topic.kinds:
                sections.append("\n## Geräte auf einen Blick\n")
                sections.append(_device_table(systems))
                if systems:
                    sections.append("\n## Die Geräte im Einzelnen\n")
                    details = _grouped_device_details if topic.slug == "container-und-vms" else _device_details
                    sections.append(details(systems, by_id, children_by_parent))
            body = "\n".join(sections)
            intro = topic.intro_hint

        db.upsert_doc_page(topic.slug, topic.title, topic.title, body.strip() + "\n", intro, topic.sort_order)
        written.append(topic.slug)
        if log:
            log(f"Kapitel geschrieben: {topic.title}")
    return written
