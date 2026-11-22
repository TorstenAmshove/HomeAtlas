"""Live, read-only access to the classic UniFi Network API for the assistant (ADR-0015).

Why a separate module: `unifi_probe.py` / `unifi_classic_probe.py` belong to the scan pipeline and
store what they find; this module answers one question at a time ("why does client X drop?") and
stores nothing. It must never import a `*_admin` module, and scan modules / `pipeline.py` must never
import it (tests/test_unifi_live.py checks both). `tools.py` may import it.

Rules enforced here:
* Auth is the integration API key as ``X-API-Key`` only -- no login, no cookie, no session.
* `_request` is the single network access. Only the fixed paths in `_ALLOWED` are reachable, with
  one validated `site` as the only caller-controlled path part; anything else raises ValueError (a
  programming error, not a user error). No redirects, no retries.
* Responses pass a per-object **allowlist of fields** (`stat/device` carries x_authkey, guest_token
  ...; a blocklist would leak the next field a UniFi update adds). Key-name redaction and removal of
  the plaintext key from strings is only the second layer.
* Errors are `UnifiLiveError` with fixed German texts -- never a response body, URL or key.
"""
from __future__ import annotations

import json
import re

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SITE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BASE = "/proxy/network"
# name -> (method, path template). The only requests this module can ever send.
_ALLOWED: dict[str, tuple[str, str]] = {
    "clients": ("GET", _BASE + "/api/s/{site}/stat/sta"),
}
MAX_CHARS = 16000
MAX_TEXT = 200
# stat/sta of a home network is a few hundred KB; anything far beyond is not a client list.
_MAX_BODY = 8_000_000
_MIN_KEY = 8

# Test hook: an httpx transport replacing the network.
_transport: httpx.AsyncBaseTransport | None = None

CLIENT_FIELDS = (
    "mac", "name", "hostname", "ip", "is_wired", "is_guest", "network", "essid", "bssid", "ap_mac",
    "radio", "radio_proto", "channel", "channel_width", "signal", "rssi", "noise", "tx_rate", "rx_rate",
    "tx_retries", "wifi_tx_retries_percentage", "tx_retry_burst_count", "roam_count", "satisfaction_avg",
    "uptime", "assoc_time", "latest_assoc_time", "first_seen", "last_seen", "disconnect_timestamp",
    "last_uplink_name", "last_uplink_mac", "blocked", "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
)
_SECRET_KEY = re.compile(r"key|token|secret|password|psk|^x_", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UnifiLiveError(Exception):
    """Carries a fixed, secret-free German message for the user/model."""


def normalize_mac(value: object) -> str:
    """'AA-BB-CC-DD-EE-FF', 'aabbccddeeff' ... -> 'aa:bb:cc:dd:ee:ff'; '' if it is not a MAC."""
    hexes = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hexes) != 12 or re.search(r"[^0-9a-fA-F:.\-\s]", str(value or "")):
        return ""
    hexes = hexes.lower()
    return ":".join(hexes[i:i + 2] for i in range(0, 12, 2))


def valid_site(site: object) -> str:
    text = "default" if site in (None, "") else site
    if not isinstance(text, str) or not _SITE.match(text):
        raise UnifiLiveError("Ungültiger Site-Name (erlaubt: Buchstaben, Ziffern, _ und -, höchstens 64 Zeichen).")
    return text


def _clean_text(value: str, api_key: str) -> str:
    text = _CONTROL.sub(" ", value)
    if api_key:
        text = text.replace(api_key, "[entfernt]")
    return text[:MAX_TEXT]


def redact(value: object, api_key: str = "") -> object:
    """Second layer: drops secret-looking keys, strips control characters and the plaintext key."""
    if isinstance(value, dict):
        return {k: redact(v, api_key) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [redact(v, api_key) for v in value]
    if isinstance(value, str):
        return _clean_text(value, api_key)
    return value


async def _request(name: str, base_url: str, api_key: str, site: str = "default") -> object:
    entry = _ALLOWED.get(name)
    if entry is None:
        raise ValueError(f"Endpunkt nicht in der Allowlist: {name}")
    method, template = entry
    if method != "GET":  # no POST endpoint is wired up yet; the events POST arrives with its tool
        raise ValueError("Nur GET ist implementiert.")
    path = template.format(site=valid_site(site))
    if not (base_url or "").strip():
        raise UnifiLiveError("Für den UniFi-Zugang ist keine URL hinterlegt.")
    if len(api_key or "") < _MIN_KEY:
        raise UnifiLiveError("UniFi-Zugang unvollständig konfiguriert (API-Key fehlt oder ist zu kurz).")
    url = base_url.strip().rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False, follow_redirects=False,
                                     headers={"X-API-Key": api_key, "Accept": "application/json"},
                                     transport=_transport) as client:
            response = await client.request(method, url)
    except httpx.TimeoutException:
        raise UnifiLiveError("Der UniFi-Controller antwortet nicht rechtzeitig.") from None
    except httpx.HTTPError:
        raise UnifiLiveError("Der UniFi-Controller ist nicht erreichbar.") from None
    status = response.status_code
    if 300 <= status < 400:
        raise UnifiLiveError("Der UniFi-Controller leitet weiter; die Adresse im Zugang prüfen.")
    if status in (401, 403):
        raise UnifiLiveError("Der UniFi-Controller verweigert den Zugriff (API-Key prüfen).")
    if status in (404, 405):
        raise UnifiLiveError("Dieser Endpunkt ist auf dieser UniFi-Version nicht verfügbar.")
    if status == 429:
        raise UnifiLiveError("Der UniFi-Controller begrenzt die Abfragen gerade; später erneut versuchen.")
    if status >= 400:
        raise UnifiLiveError("Der UniFi-Controller meldet einen Fehler.")
    if len(response.content) > _MAX_BODY:
        raise UnifiLiveError("Die Antwort des UniFi-Controllers ist zu groß.")
    try:
        return response.json()
    except ValueError:
        raise UnifiLiveError("Unerwartete Antwort des UniFi-Controllers.") from None


def _data_list(body: object) -> list[dict]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise UnifiLiveError("Unerwartete Antwort des UniFi-Controllers.")
    return [d for d in data if isinstance(d, dict)]


def _pick(entry: dict, fields: tuple[str, ...], api_key: str) -> dict:
    """Allowlisted fields with scalar values only (every allowlisted field is a scalar), so each value
    is at most MAX_TEXT characters and the result stays far below MAX_CHARS."""
    picked = {f: entry[f] for f in fields
              if f in entry and (entry[f] is None or isinstance(entry[f], (str, int, float, bool)))}
    return redact(picked, api_key)  # type: ignore[return-value]


def _bounded(result: dict) -> dict:
    """Enforces MAX_CHARS on the serialized result (valid JSON, never cut mid-object)."""
    if len(json.dumps(result, ensure_ascii=False)) > MAX_CHARS:
        raise UnifiLiveError("Die Antwort des UniFi-Controllers ist zu groß.")
    return result


def _matches(entry: dict, macs: set[str], ips: set[str], names: set[str]) -> bool:
    if normalize_mac(entry.get("mac")) in macs:
        return True
    if str(entry.get("ip") or "") in ips:
        return True
    return any(str(entry.get(k) or "").strip().lower() in names for k in ("name", "hostname"))


async def client_status(base_url: str, api_key: str, *, macs: set[str], ips: set[str], names: set[str],
                        site: object = "default") -> dict:
    """Live radio/uplink values of one currently connected client (stat/sta).

    `macs` are normalised, `names` lower-case; the caller resolves the user's text to these
    identifiers (tools.py). Several matching clients -> candidates, never a guess."""
    body = await _request("clients", base_url, api_key, valid_site(site))
    found = [e for e in _data_list(body) if _matches(e, macs, ips, names)]
    if not found:
        return {"verbunden": False,
                "hinweis": ("Der Client ist aktuell nicht beim UniFi-Controller verbunden (stat/sta zeigt nur "
                            "verbundene Clients). Mögliche Gründe: ausgeschaltet, außer Reichweite oder falsche Angabe.")}
    if len(found) > 1:
        return _bounded({"verbunden": None, "mehrdeutig": True,
                         "kandidaten": [_pick(e, ("name", "hostname", "mac", "ip"), api_key) for e in found[:10]],
                         "hinweis": "Mehrere Clients passen; bitte die MAC-Adresse angeben."})
    entry = found[0]
    result = {"verbunden": True, "client": _pick(entry, CLIENT_FIELDS, api_key)}
    if entry.get("is_wired"):
        result["hinweis"] = "Kabelgebundener Client: keine Funkwerte (Signal, Retries, Roaming) vorhanden."
    elif "signal" not in entry and "rssi" not in entry:
        result["hinweis"] = "Der Controller lieferte für diesen WLAN-Client keine Funkwerte."
    return _bounded(result)
