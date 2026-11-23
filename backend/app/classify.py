"""LLM-assisted identification of discovered devices.

Discovery already produces a rule-based guess (see `discovery._guess`); this refines it using the
evidence a fingerprint table can't reason about -- an unfamiliar mDNS service name, a vendor
string plus an unusual port combination, a web page title in a foreign language.

Deliberately additive, never destructive:

* It runs only over devices the rules were unsure about, so a confidently-identified FRITZ!Box
  doesn't cost tokens.
* A low-confidence answer is discarded rather than written -- the rule-based guess is a better
  default than a shrug.
* It never renames or re-kinds a device whose name comes from a source (manual, UniFi, Docker,
  Proxmox, Omada). A name the device reports itself (UPnP friendlyName, mDNS, Shelly app name,
  recorded by discovery as `extra.nameSource`) is protected too, but only the name: such names
  say little about the device type, so the model may still set `kind`. Docker containers are skipped entirely: they all share the host's IP, and the
  answers are mapped back per IP, so one answer would otherwise hit every container of that host.
* Failure of the whole step is non-fatal: the scan completes with rule-based results and a warning.
"""
from __future__ import annotations

import asyncio
import json
import re

from . import llm_providers, prompts, vendor_docs

# Small enough that one bad batch loses little work, large enough to amortize the prompt.
_BATCH_SIZE = 10

_VALID_KINDS = {
    "router", "network", "server", "nas", "container", "vm", "pc", "mobile", "printer", "camera",
    "smarthome", "climate", "heating", "energy", "media", "iot", "other",
}
_VALID_IMPORTANCE = {"critical", "normal", "low"}
_ACCEPTED_CONFIDENCE = {"high", "medium"}


_NAME_SOURCES = ("docker", "proxmox", "unifi", "omada")
# Values of `extra.nameSource` (set by discovery) for names the device reported itself.
_SELF_REPORTED = ("upnp", "mdns", "shelly")


def is_container(finding: dict) -> bool:
    return "docker" in (finding.get("extra") or {})


def has_source_name(finding: dict) -> bool:
    """True if a source other than a guess supplied this device's name and kind."""
    tokens = set((finding.get("discoverySource") or "").split("+"))
    extra = finding.get("extra") or {}
    return bool(tokens.intersection(_NAME_SOURCES)) or any(key in extra for key in _NAME_SOURCES)


def has_self_reported_name(finding: dict) -> bool:
    """True if the current name is one the device reported itself (UPnP, mDNS, Shelly app)."""
    return (finding.get("extra") or {}).get("nameSource") in _SELF_REPORTED


def has_evidence(finding: dict) -> bool:
    extra = finding.get("extra") or {}
    return bool(
        finding.get("openPorts") or finding.get("vendor") or finding.get("hostname")
        or extra.get("mdns") or extra.get("ssdp") or extra.get("httpBanner")
    )


def needs_classification(finding: dict) -> bool:
    """Which devices are worth an LLM call.

    Requires evidence first: a silent host with no ports, no name and no vendor gives the model
    nothing but an IP address, and asking anyway invites a confident invention.

    Given evidence, a device qualifies if the rules couldn't place it, if their guess was only a
    placeholder (`guessConfident`), or if it still lacks a purpose -- that is what makes the
    inventory readable, so it is worth filling even for hardware that was recognised. A missing
    manufacturer link alone is not enough (every non-AVM router lacks one).
    """
    if is_container(finding):
        return False
    evidence = finding.get("extra") or {}
    if not has_evidence(finding):
        return False
    if finding.get("kind") in ("other", ""):
        return True
    if not evidence.get("guessConfident", True):
        return True
    return not finding.get("purpose")


def _evidence_for(finding: dict) -> dict:
    extra = finding.get("extra") or {}
    banner = extra.get("httpBanner") or {}
    return {
        "ip": finding.get("ip", ""),
        "hostname": finding.get("hostname", ""),
        "macVendor": finding.get("vendor", ""),
        # What the rules already concluded. Given to the model so it corrects or completes rather
        # than starting from scratch -- and so it can leave a confident identification alone.
        "bisherigeEinordnung": finding.get("kind", ""),
        "bisherigerZweck": finding.get("purpose", ""),
        "openPorts": [
            f"{s['port']} ({s['service']})" for s in (finding.get("services") or [])
        ][:20],
        "mdnsServices": [
            {"type": e.get("type", ""), "name": e.get("name", "")} for e in (extra.get("mdns") or [])
        ][:8],
        "upnp": [
            e.get("description") for e in (extra.get("ssdp") or []) if e.get("description")
        ][:4],
        "upnpServer": next((e.get("server", "") for e in (extra.get("ssdp") or []) if e.get("server")), ""),
        "webPageTitle": banner.get("title", ""),
        "webServerHeader": banner.get("server", ""),
    }


def _merge_by_ip(candidates: list[dict]) -> list[dict]:
    """One evidence record per IP. A network finding and a controller/Proxmox finding for the same
    address would otherwise yield competing records (last one wins). Scalars come from the first
    finding with a value, lists are united in order without duplicates. Findings without an IP
    cannot be mapped back to an answer and are skipped."""
    merged: dict[str, dict] = {}
    for f in candidates:
        ip = f.get("ip") or ""
        if not ip:
            continue
        m = merged.get(ip)
        if m is None:
            merged[ip] = {**f, "services": list(f.get("services") or []),
                          "extra": {**(f.get("extra") or {}),
                                    "mdns": list((f.get("extra") or {}).get("mdns") or []),
                                    "ssdp": list((f.get("extra") or {}).get("ssdp") or [])}}
            continue
        for key in ("hostname", "vendor"):
            if not m.get(key) and f.get(key):
                m[key] = f[key]
        if not m.get("purpose") and f.get("purpose"):
            m["purpose"] = f["purpose"]
        if m.get("kind") in ("other", "", None) and f.get("kind") not in ("other", "", None):
            m["kind"] = f["kind"]
        extra = f.get("extra") or {}
        for target, items in ((m["services"], f.get("services") or []),
                              (m["extra"]["mdns"], extra.get("mdns") or []),
                              (m["extra"]["ssdp"], extra.get("ssdp") or [])):
            for item in items:
                if item not in target:
                    target.append(item)
        for key in ("httpBanner",):
            if not m["extra"].get(key) and extra.get(key):
                m["extra"][key] = extra[key]
    return list(merged.values())


def _extract_json_array(text: str) -> list:
    """Models wrap JSON in prose or ```json fences often enough that a bare `json.loads` fails on
    otherwise perfect answers. Cut to the outermost array before parsing."""
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("Antwort enthielt kein JSON-Array.")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, list):
        raise ValueError("Antwort war kein JSON-Array.")
    return value


async def classify(findings: list[dict], settings: dict, log=None,
                   force: bool = False) -> tuple[dict[str, dict], list[str]]:
    """Returns (by_ip, warnings). `by_ip` holds only entries worth applying.

    `force` (manual per-device request) skips only the "is the guess unsure / purpose missing"
    test; containers and findings without any evidence stay excluded."""
    warnings: list[str] = []
    if force:
        candidates = [f for f in findings if not is_container(f) and has_evidence(f)]
    else:
        candidates = [f for f in findings if needs_classification(f)]
    if not candidates:
        return {}, warnings
    if not llm_providers.is_configured(settings.get("llmProvider", ""), settings):
        # Never send device evidence to a provider nobody configured (the default provider has no
        # key on a fresh install); the rule-based guess stays.
        warnings.append("KI-Einordnung übersprungen: Für den gewählten KI-Anbieter ist kein Zugang "
                        "eingerichtet (Einstellungen -> KI-Assistent).")
        if log:
            log("KI-Einordnung übersprungen: kein KI-Zugang eingerichtet.")
        return {}, warnings

    candidates = _merge_by_ip(candidates)
    if not candidates:
        return {}, warnings

    by_ip: dict[str, dict] = {}
    for offset in range(0, len(candidates), _BATCH_SIZE):
        batch = candidates[offset:offset + _BATCH_SIZE]
        payload = json.dumps([_evidence_for(f) for f in batch], ensure_ascii=False, indent=1)
        try:
            result = await llm_providers.chat(
                settings.get("llmProvider", ""), settings, prompts.CLASSIFY_SYSTEM,
                [{"role": "user", "content": f"Ordne diese {len(batch)} Geräte ein:\n\n{payload}"}],
                purpose="CHAT",
            )
            entries = _extract_json_array(result.text)
        except (llm_providers.ProviderError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"KI-Einordnung für {len(batch)} Geräte fehlgeschlagen: {exc}")
            if log:
                log(f"KI-Einordnung fehlgeschlagen: {exc}")
            continue

        known_ips = {f["ip"] for f in batch}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ip = str(entry.get("ip", "")).strip()
            # Guard against the model answering about a device that wasn't in this batch.
            raw_conf = entry.get("confidence")
            confidence = "medium" if raw_conf is None or raw_conf == "" else str(raw_conf).strip().lower()
            if ip not in known_ips or confidence not in _ACCEPTED_CONFIDENCE:
                continue
            # Invalid values stay empty so `apply` never overwrites a rule result with a default.
            kind = entry.get("kind") if entry.get("kind") in _VALID_KINDS else ""
            importance = entry.get("importance") if entry.get("importance") in _VALID_IMPORTANCE else ""
            by_ip[ip] = {
                "kind": kind,
                "name": str(entry.get("name") or "").strip()[:80],
                "vendor": str(entry.get("vendor") or "").strip()[:80],
                "model": str(entry.get("model") or "").strip()[:100],
                "purpose": str(entry.get("purpose") or "").strip()[:200],
                "descriptionMd": str(entry.get("description") or "").strip()[:800],
                "docUrl": str(entry.get("docUrl") or "").strip()[:300],
                "importance": importance,
                "confidence": confidence,
            }
        if log:
            log(f"KI-Einordnung: {len(batch)} Geräte geprüft")

    await _drop_dead_links(by_ip, warnings, log)
    return by_ip, warnings


async def _drop_dead_links(by_ip: dict[str, dict], warnings: list[str], log) -> None:
    """Checks every LLM-suggested documentation link and removes the ones that don't answer.

    This is not optional politeness. A model asked for a manual URL produces a plausible, correctly
    structured, frequently non-existent one, and the place those links surface is the chapter
    someone reads while something is broken. A missing link is a small gap; a link that 404s costs
    real time at the worst moment.
    """
    candidates = {ip: data["docUrl"] for ip, data in by_ip.items() if data.get("docUrl")}
    if not candidates:
        return
    checks = await asyncio.gather(
        *(vendor_docs.validate(url) for url in candidates.values()), return_exceptions=True
    )
    dropped = 0
    for (ip, url), ok in zip(candidates.items(), checks):
        if ok is not True:
            by_ip[ip]["docUrl"] = ""
            dropped += 1
    if dropped:
        message = f"{dropped} von {len(candidates)} vorgeschlagenen Hersteller-Links waren nicht erreichbar und wurden verworfen."
        warnings.append(message)
        if log:
            log(message)


def apply(finding: dict, classification: dict) -> dict:
    """Merges one classification into a finding. Empty strings from the model never overwrite a
    value the rules already found -- a blank answer is an absence of information, not a correction."""
    if is_container(finding):
        return finding
    if has_source_name(finding):
        protected = ("kind", "name")
    elif has_self_reported_name(finding):
        protected = ("name",)
    else:
        protected = ()
    # A kind the rules were sure about is not the model's to change, whoever supplied the name.
    if (finding.get("kind") not in ("other", "", None)
            and (finding.get("extra") or {}).get("guessConfident", True)):
        protected = tuple({*protected, "kind"})
    # Never demote a rule-assigned critical (gateway); the model may still raise to critical.
    if finding.get("importance") == "critical":
        protected = tuple({*protected, "importance"})
    merged = dict(finding)
    for field in ("kind", "name", "vendor", "model", "purpose", "descriptionMd", "importance", "docUrl"):
        value = classification.get(field)
        if value and field not in protected:
            merged[field] = value
    # A curated link always beats a suggested one -- it was verified by a human, not by an HTTP 200.
    if finding.get("docUrl"):
        merged["docUrl"] = finding["docUrl"]
    merged["discoverySource"] = f"{finding.get('discoverySource', '')}+ki".strip("+")
    merged["extra"] = {**(finding.get("extra") or {}),
                       "aiConfidence": classification.get("confidence", "medium")}
    return merged


_AI_FILL_FIELDS = ("vendor", "model", "purpose", "descriptionMd", "docUrl")


def finding_from_system(system: dict) -> dict:
    """Builds the finding-shaped dict `classify`/`apply` work on from a stored inventory row."""
    return {key: system.get(key) for key in (
        "ip", "hostname", "vendor", "kind", "purpose", "docUrl", "openPorts", "services",
        "discoverySource", "name", "importance",
    )} | {"extra": system.get("extra") or {}}


def apply_to_system(system: dict, classification: dict) -> dict:
    """Patch (for `db.update_system`) that applies one classification to a stored row.

    Unconfirmed rows get exactly what `apply` would give a finding (source/self-reported name
    protection included). Confirmed rows only get still-empty vendor/model/purpose/description/link
    fields -- never kind, name or importance. A link the row already has (`docUrl`/`docLink`)
    beats the suggested one. Returns {} if there is nothing to change."""
    finding = finding_from_system(system)
    if is_container(finding):
        return {}
    if system.get("docLink") and not finding.get("docUrl"):
        finding["docUrl"] = system["docLink"]
    merged = apply(finding, classification)
    if system.get("confirmed"):
        fields = [f for f in _AI_FILL_FIELDS if not system.get(f) and merged.get(f)
                  and not (f == "docUrl" and system.get("docLink"))]
    else:
        fields = [f for f in ("kind", "name", "vendor", "model", "purpose", "descriptionMd",
                              "importance", "docUrl")
                  if merged.get(f) and merged.get(f) != system.get(f)
                  and not (f == "docUrl" and system.get("docLink") and not system.get("docUrl"))]
    if not fields:
        return {}
    patch = {f: merged[f] for f in fields}
    source = system.get("discoverySource") or ""
    patch["discoverySource"] = source if "ki" in source.split("+") else merged["discoverySource"]
    patch["extra"] = {**(system.get("extra") or {}),
                      "aiConfidence": classification.get("confidence", "medium")}
    return patch
