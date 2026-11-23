"""MAC address -> hardware vendor.

The authoritative source is the IEEE OUI registry, which is far too large to bundle and changes
constantly, so it is downloaded on demand into the data volume (Einstellungen -> Netzwerk-Scan ->
"Hersteller-Datenbank aktualisieren", and automatically on a scan while none is loaded, at most
once per 24 h so an offline host does not wait on the download every time). Until that succeeds `_FALLBACK` covers a short list of prefixes common in German
households -- deliberately short, because a *wrong* vendor is worse than none here: the vendor
string is fed to the LLM as evidence when it classifies a device, so a bad guess propagates into
the documentation.

Note that vendor is only ever a hint anyway. mDNS/SSDP names and UPnP `manufacturer`/`modelName`
are authoritative when present and take precedence in discovery.py.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path

import httpx

_CACHE_PATH = Path(os.environ.get("HOMEATLAS_OUI_PATH", "/data/oui.json"))
_IEEE_URL = "https://standards-oui.ieee.org/oui/oui.csv"

# Prefixes verifiable from the devices themselves and stable for decades. Keep this list small
# and only add entries you are sure of.
_FALLBACK: dict[str, str] = {
    "00:04:0E": "AVM (Fritz!Box)",
    "00:1B:63": "Apple",
    "00:03:93": "Apple",
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Trading",
    "E4:5F:01": "Raspberry Pi Trading",
    "00:50:56": "VMware (virtuelle Maschine)",
    "00:0C:29": "VMware (virtuelle Maschine)",
    "00:15:5D": "Microsoft Hyper-V (virtuelle Maschine)",
    "08:00:27": "Oracle VirtualBox (virtuelle Maschine)",
    "52:54:00": "QEMU/KVM (virtuelle Maschine)",
    "02:42:AC": "Docker-Container",
}

_loaded: dict[str, str] | None = None
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")


def normalize_mac(mac: str) -> str:
    """Lowercase colon form, or "" if this isn't a usable MAC. Randomized/locally-administered
    addresses (the privacy MACs phones use) are kept -- they still identify the device for as long
    as it holds that address, which is what re-discovery needs."""
    mac = (mac or "").strip().lower().replace("-", ":")
    return mac if _MAC_RE.match(mac) else ""


def real_name(name: str | None) -> str:
    """`name` stripped, or "" if it is only a MAC address. Controllers report the MAC as the name
    of a client nobody named; that identifies the device but says nothing a real name would."""
    name = (name or "").strip()
    return "" if normalize_mac(name) else name


def _prefix(mac: str) -> str:
    return mac.upper()[:8]


def _load() -> dict[str, str]:
    global _loaded
    if _loaded is not None:
        return _loaded
    table = dict(_FALLBACK)
    if _CACHE_PATH.exists():
        try:
            downloaded = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(downloaded, dict):
                # Downloaded IEEE data wins over the hand-maintained fallback.
                table.update(downloaded)
        except (json.JSONDecodeError, OSError):
            pass
    _loaded = table
    return table


def lookup(mac: str) -> str:
    mac = normalize_mac(mac)
    if not mac:
        return ""
    if mac.startswith("02:42:"):
        return "Docker-Container"
    return _load().get(_prefix(mac), "")


def is_locally_administered(mac: str) -> bool:
    """True for randomized MACs (bit 1 of the first octet). Worth surfacing: iPhones and modern
    Androids rotate these per WLAN, so such a device may show up as "new" after a while."""
    mac = normalize_mac(mac)
    if not mac:
        return False
    try:
        return bool(int(mac[:2], 16) & 0b10)
    except ValueError:
        return False


def _attempt_path() -> Path:
    # Derived at call time so a patched _CACHE_PATH moves the marker with it.
    return _CACHE_PATH.with_name("oui.attempt")


def download_due(now: float | None = None, min_interval: int = 86400) -> bool:
    """False if a download failed less than `min_interval` seconds ago. Unreadable marker or a
    timestamp in the future counts as due."""
    try:
        last = float(_attempt_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    current = time.time() if now is None else now
    return not (0 <= current - last < min_interval)


def _mark_attempt() -> None:
    try:
        _attempt_path().parent.mkdir(parents=True, exist_ok=True)
        _attempt_path().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


async def refresh_from_ieee() -> tuple[bool, str]:
    """Downloads and caches the IEEE registry. Returns (ok, message). A failure is recorded so the
    scan does not retry within 24 h; success clears that record."""
    ok, message = await _refresh_from_ieee()
    if ok:
        try:
            _attempt_path().unlink(missing_ok=True)
        except OSError:
            pass
    else:
        _mark_attempt()
    return ok, message


async def _refresh_from_ieee() -> tuple[bool, str]:
    global _loaded
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True) as client:
            resp = await client.get(
                _IEEE_URL,
                headers={"User-Agent": "HomeAtlas/1.0 (+https://github.com/TorstenAmshove/HomeAtlas)"},
            )
        if resp.status_code >= 400:
            return False, f"IEEE-Server antwortete mit HTTP {resp.status_code}."
    except httpx.HTTPError as exc:
        return False, f"Download nicht möglich: {exc}"

    table: dict[str, str] = {}
    reader = csv.reader(resp.text.splitlines())
    for row in reader:
        # Columns are Registry,Assignment,Organization Name,Address -- but rather than trusting
        # that order, pick the first 6-hex-digit cell as the assignment and the next non-empty
        # cell as the name, so a column reshuffle upstream doesn't silently produce garbage.
        assignment = next((c.strip() for c in row if re.fullmatch(r"[0-9A-Fa-f]{6}", c.strip())), None)
        if assignment is None:
            continue
        index = next(i for i, c in enumerate(row) if c.strip().upper() == assignment.upper())
        name = next((c.strip() for c in row[index + 1:] if c.strip()), "")
        if not name:
            continue
        upper = assignment.upper()
        table[f"{upper[0:2]}:{upper[2:4]}:{upper[4:6]}"] = name

    if len(table) < 1000:
        return False, f"Antwort sah nicht wie die IEEE-Datenbank aus (nur {len(table)} Einträge erkannt)."
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return False, f"Konnte die Datenbank nicht speichern: {exc}"
    _loaded = None
    return True, f"{len(table):,} Hersteller-Einträge gespeichert.".replace(",", ".")


def is_downloaded() -> bool:
    return _CACHE_PATH.exists()


def entry_count() -> int:
    return len(_load())
