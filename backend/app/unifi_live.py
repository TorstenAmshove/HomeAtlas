"""Live, read-only access to the classic UniFi Network API for the assistant (ADR-0015, ADR-0016).

Why a separate module: `unifi_probe.py` / `unifi_classic_probe.py` belong to the scan pipeline and
store what they find; this module answers one question at a time ("why does client X drop?") and
stores nothing. It must never import a `*_admin` module, and scan modules / `pipeline.py` must never
import it (tests/test_unifi_live.py checks both). `tools.py` may import it (as it may `proxmox_live`).

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
import math
import re
import time

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_TIMEOUT_POST = httpx.Timeout(30.0, connect=5.0)  # the event log query is slow
_SITE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BASE = "/proxy/network"
# name -> (method, path template). The only requests this module can ever send.
_ALLOWED: dict[str, tuple[str, str]] = {
    "clients": ("GET", _BASE + "/api/s/{site}/stat/sta"),
    "devices": ("GET", _BASE + "/api/s/{site}/stat/device"),
    "health": ("GET", _BASE + "/api/s/{site}/stat/health"),
    "firewall_policies": ("GET", _BASE + "/v2/api/site/{site}/firewall-policies"),
    "firewall_zones": ("GET", _BASE + "/v2/api/site/{site}/firewall/zone"),
    # The one POST (ADR-0015): a read-only log query with a filter body built from internal integers.
    "events": ("POST", _BASE + "/v2/api/site/{site}/system-log/all"),
}
_EVENT_BODY_KEYS = {"timestampFrom", "timestampTo", "pageNumber", "pageSize"}
MAX_ENTRIES = 50
MAX_HOURS = 168
DEFAULT_HOURS = 24
MAX_EVENT_PAGES = 5
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
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
DEVICE_FIELDS = ("mac", "name", "model", "type", "version", "state", "ip", "uptime", "last_seen", "num_sta",
                 "satisfaction", "upgradable")
PORT_FIELDS = ("port_idx", "name", "up", "speed", "full_duplex", "is_uplink", "rx_errors", "tx_errors",
               "rx_dropped", "tx_dropped", "link_down_count", "poe_good", "stp_state_change_count")
RADIO_FIELDS = ("name", "radio", "channel", "num_sta", "cu_total", "cu_interf", "satisfaction", "tx_retries_pct",
                "tx_power")
UPLINK_FIELDS = ("name", "up", "speed", "latency", "drops", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped",
                 "uptime", "uplink_device_name")
_MAX_NESTED = 24
HEALTH_FIELDS = {
    "wlan": (), "lan": (), "vpn": (),
    "wan": ("isp_name", "uptime_stats", "num_gw"),
    "www": ("latency", "drops", "uptime", "xput_down", "xput_up", "speedtest_ping", "speedtest_lastrun",
            "speedtest_status"),
}
POLICY_FIELDS = ("name", "action", "enabled", "hits", "index", "predefined", "protocol", "ip_version", "logging")
# The event's `key` (e.g. CLIENT_DISCONNECTED_WIRELESS_2) is an identifier, but the second redaction
# layer drops every field whose name contains "key"; it is therefore emitted as `kennung`.
EVENT_FIELDS = ("timestamp", "category", "subcategory", "severity", "type", "event", "title_raw", "message_raw")
EVENT_PARAMS = ("CHANNEL", "CHANNEL_WIDTH", "RADIO_BAND", "AVG_INTERFERENCE", "AVG_UTILIZATION", "DURATION",
                "WLAN", "NETWORK", "SIGNAL_STRENGTH", "CLIENT", "SRC_CLIENT", "DEVICE")
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


async def _request(name: str, base_url: str, api_key: str, site: str = "default",
                   body: dict | None = None) -> object:
    entry = _ALLOWED.get(name)
    if entry is None:
        raise ValueError(f"Endpunkt nicht in der Allowlist: {name}")
    method, template = entry
    if method == "POST":
        ok = (isinstance(body, dict) and set(body) == _EVENT_BODY_KEYS
              and all(type(v) is int and v >= 0 for v in body.values())
              and 1 <= body["pageSize"] <= MAX_ENTRIES and body["timestampFrom"] <= body["timestampTo"])
        if not ok:
            raise ValueError("Ungültiger Abfrage-Body.")
    elif method != "GET" or body is not None:
        raise ValueError("Nur GET ohne Body ist für diesen Endpunkt erlaubt.")
    path = template.format(site=valid_site(site))
    if not (base_url or "").strip():
        raise UnifiLiveError("Für den UniFi-Zugang ist keine URL hinterlegt.")
    if len(api_key or "") < _MIN_KEY:
        raise UnifiLiveError("UniFi-Zugang unvollständig konfiguriert (API-Key fehlt oder ist zu kurz).")
    url = base_url.strip().rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_POST if method == "POST" else _TIMEOUT, verify=False, follow_redirects=False,
                                     headers={"X-API-Key": api_key, "Accept": "application/json"},
                                     transport=_transport) as client:
            response = await client.request(method, url, json=body) if body is not None \
                else await client.request(method, url)
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


def _scalar_dict(value: object, api_key: str) -> dict:
    """Scalar entries of a nested stats object (sys_stats ...); nested structures are dropped."""
    if not isinstance(value, dict):
        return {}
    return _pick(value, tuple(k for k in value if isinstance(k, str)), api_key)


def _nested_list(value: object, fields: tuple[str, ...], api_key: str) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [_pick(e, fields, api_key) for e in value[:_MAX_NESTED] if isinstance(e, dict)]


def _device_summary(entry: dict, api_key: str) -> dict:
    return _pick(entry, ("name", "model", "type", "state", "num_sta", "uptime", "mac", "ip"), api_key)


def _device_detail(entry: dict, api_key: str) -> dict:
    detail = _pick(entry, DEVICE_FIELDS, api_key)
    for key in ("sys_stats", "system-stats"):
        stats = _scalar_dict(entry.get(key), api_key)
        if stats:
            detail[key] = stats
    ports = _nested_list(entry.get("port_table"), PORT_FIELDS, api_key)
    if ports:
        detail["port_table"] = ports
    radios = _nested_list(entry.get("radio_table_stats"), RADIO_FIELDS, api_key)
    if radios:
        detail["radio_table_stats"] = radios
    if isinstance(entry.get("uplink"), dict):
        detail["uplink"] = _pick(entry["uplink"], UPLINK_FIELDS, api_key)
    for key, source in (("port_table", "port_table"), ("radio_table_stats", "radio_table_stats")):
        if isinstance(entry.get(source), list) and len(entry[source]) > _MAX_NESTED:
            detail["gekuerzt"] = True
    return detail


async def device_status(base_url: str, api_key: str, *, macs: set[str] | None = None, ips: set[str] | None = None,
                        names: set[str] | None = None, overview: bool = False, site: object = "default") -> dict:
    """Live status of UniFi devices (stat/device): one device in detail, or a short overview."""
    body = await _request("devices", base_url, api_key, valid_site(site))
    devices = _data_list(body)
    if overview:
        result = {"geraete": [_device_summary(e, api_key) for e in devices[:MAX_ENTRIES]]}
        if len(devices) > MAX_ENTRIES:
            result["gekuerzt"] = True
            result["hinweis"] = f"Nur die ersten {MAX_ENTRIES} von {len(devices)} Geräten."
        return _bounded(result)
    found = [e for e in devices if _matches(e, macs or set(), ips or set(), names or set())]
    if not found:
        return {"gefunden": False,
                "hinweis": "Kein UniFi-Gerät mit dieser Angabe. Ohne Angabe gibt das Werkzeug eine Übersicht.",
                "geraete": [_pick(e, ("name", "mac"), api_key) for e in devices[:MAX_ENTRIES]]}
    if len(found) > 1:
        return _bounded({"gefunden": None, "mehrdeutig": True,
                         "kandidaten": [_pick(e, ("name", "model", "mac", "ip"), api_key) for e in found[:10]],
                         "hinweis": "Mehrere Geräte passen; bitte die MAC-Adresse angeben."})
    return _bounded({"gefunden": True, "geraet": _device_detail(found[0], api_key)})


def _health_entry(entry: dict, api_key: str) -> dict:
    sub = entry.get("subsystem")
    fields = ["subsystem", "status", "rx_bytes-r", "tx_bytes-r"]
    fields += [k for k in entry if isinstance(k, str) and k.startswith("num_")]
    fields += HEALTH_FIELDS.get(sub, ()) if isinstance(sub, str) else ()
    picked = _pick(entry, tuple(fields), api_key)
    for key in ("uptime_stats",):  # nested per-period stats: keep scalar sub-values only
        if isinstance(entry.get(key), dict):
            picked[key] = {k: v for k, v in _scalar_dict(
                {a: b for a, b in entry[key].items() if isinstance(b, (int, float, str, bool))}, api_key).items()}
    return picked


def _zone_name(zone_id: object, zones: dict[str, str]) -> str:
    return zones.get(zone_id, "unbekannt") if isinstance(zone_id, str) else "unbekannt"


def _firewall_summary(policies: object, zones_body: object, api_key: str) -> dict:
    if not isinstance(policies, list):
        raise UnifiLiveError("Unerwartete Antwort des UniFi-Controllers.")
    zones = {}
    if isinstance(zones_body, list):
        zones = {z["_id"]: str(z.get("name") or "unbekannt") for z in zones_body
                 if isinstance(z, dict) and isinstance(z.get("_id"), str)}
    rows = [p for p in policies if isinstance(p, dict)]
    by_action: dict[str, int] = {}
    for p in rows:
        action = str(p.get("action") or "unbekannt")[:40]
        by_action[action] = by_action.get(action, 0) + 1

    def hits(p: dict) -> int:
        v = p.get("hits")
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    top = []
    for p in sorted(rows, key=hits, reverse=True)[:MAX_ENTRIES]:
        row = _pick(p, POLICY_FIELDS, api_key)
        row["hits"] = hits(p)
        src = p.get("source") if isinstance(p.get("source"), dict) else {}
        dst = p.get("destination") if isinstance(p.get("destination"), dict) else {}
        row["von_zone"] = _zone_name(src.get("zone_id"), zones)
        row["nach_zone"] = _zone_name(dst.get("zone_id"), zones)
        top.append(row)
    return {"anzahl": len(rows), "je_aktion": by_action, "meistgenutzt": top,
            "hinweis": f"Nur die {MAX_ENTRIES} Regeln mit den meisten Treffern; keine Adress- oder Portlisten."}


async def network_status(base_url: str, api_key: str, *, site: object = "default") -> dict:
    """WAN/LAN/WLAN/VPN health (stat/health) and a firewall summary (v2 policies + zones)."""
    site = valid_site(site)
    health = _data_list(await _request("health", base_url, api_key, site))
    result: dict = {"gesundheit": [_health_entry(e, api_key) for e in health[:MAX_ENTRIES]]}
    try:
        policies = await _request("firewall_policies", base_url, api_key, site)
        try:
            zones = await _request("firewall_zones", base_url, api_key, site)
        except UnifiLiveError:
            zones = None  # zone names are only a nicety; policies stay useful
        result["firewall"] = _firewall_summary(policies, zones, api_key)
    except UnifiLiveError as exc:
        result["firewall"] = {"fehler": str(exc)}
    return _bounded(result)


def clamp_hours(value: object) -> int:
    """Window in hours: default 24, at most 168 (7 days); junk (bool, nan, inf, text, <= 0) -> default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_HOURS
    if isinstance(value, float) and not math.isfinite(value):
        return DEFAULT_HOURS
    hours = round(value)
    if hours <= 0:
        return DEFAULT_HOURS
    return min(hours, MAX_HOURS)


def _clamp_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (
            isinstance(value, float) and not math.isfinite(value)):
        return 20
    return max(1, min(MAX_ENTRIES, round(value)))


def _event_params(params: object, api_key: str) -> dict:
    """Only the `name` of allowlisted parameter objects (plus `id` for clients if it is a MAC)."""
    if not isinstance(params, dict):
        return {}
    out = {}
    for key in EVENT_PARAMS:
        obj = params.get(key)
        if not isinstance(obj, dict):
            continue
        item = {}
        name = obj.get("name")
        if isinstance(name, (str, int, float)) and not isinstance(name, bool):
            item["name"] = redact(str(name), api_key)
        if key in ("CLIENT", "SRC_CLIENT") and normalize_mac(obj.get("id")):
            item["id"] = normalize_mac(obj.get("id"))
        if item:
            out[key] = item
    return out


def _event_matches(params: object, macs: set[str], ips: set[str], names: set[str]) -> bool:
    if not isinstance(params, dict):
        return False
    for key in ("CLIENT", "SRC_CLIENT"):
        obj = params.get(key)
        if isinstance(obj, dict) and _matches({"mac": obj.get("id"), "ip": obj.get("ip"), "name": obj.get("name"),
                                               "hostname": obj.get("hostname")}, macs, ips, names):
            return True
    return False


async def events(base_url: str, api_key: str, *, hours: object = None, client: bool = False,
                 macs: set[str] | None = None, ips: set[str] | None = None, names: set[str] | None = None,
                 severity: object = None, limit: object = None, site: object = "default") -> dict:
    """Controller events of the last `hours` (<= 168), newest first, optionally for one client.

    Pages are fetched newest to oldest, at most MAX_EVENT_PAGES; the client/severity filters run
    locally, so the result states how many events were actually searched."""
    site = valid_site(site)
    sev = None
    if severity not in (None, ""):
        sev = severity.upper() if isinstance(severity, str) else ""
        if sev not in SEVERITIES:
            raise UnifiLiveError("Ungültige severity (erlaubt: " + ", ".join(SEVERITIES) + ").")
    window = clamp_hours(hours)
    cap = _clamp_limit(limit)
    now = int(time.time() * 1000)
    start = now - window * 3600 * 1000
    found: list[dict] = []
    seen: set[tuple] = set()
    searched = total = pages_total = 0
    note = ""
    for page in range(MAX_EVENT_PAGES):
        try:
            body = await _request("events", base_url, api_key, site, {
                "timestampFrom": start, "timestampTo": now, "pageNumber": page, "pageSize": MAX_ENTRIES})
        except UnifiLiveError as exc:
            if page == 0:
                raise
            note = f"Teilergebnis: Seite {page + 1} nicht abrufbar ({exc})"
            break
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            if page == 0:
                raise UnifiLiveError("Unerwartete Antwort des UniFi-Controllers.")
            break
        total = body.get("total_element_count") if isinstance(body.get("total_element_count"), int) else total
        pages_total = body.get("total_page_count") if isinstance(body.get("total_page_count"), int) else 0
        for ev in (e for e in data if isinstance(e, dict)):
            searched += 1
            if ev.get("category") == "AUDIT":
                continue
            ident = (ev.get("key"), ev.get("timestamp"))
            if ident in seen:
                continue
            seen.add(ident)
            if sev and str(ev.get("severity") or "").upper() != sev:
                continue
            if client and not _event_matches(ev.get("parameters"), macs or set(), ips or set(), names or set()):
                continue
            row = _pick(ev, EVENT_FIELDS, api_key)
            if isinstance(ev.get("key"), str):
                row["kennung"] = _clean_text(ev["key"], api_key)
            params = _event_params(ev.get("parameters"), api_key)
            if params:
                row["parameter"] = params
            found.append(row)
        if len(found) >= cap or page + 1 >= pages_total or not data:
            break
    result: dict = {"fenster_stunden": window, "durchsucht": searched, "gesamt_im_fenster": total,
                    "treffer": len(found[:cap]), "ereignisse": found[:cap]}
    hints = [note] if note else []
    if client or sev:
        hints.append("Kein Treffer heißt nicht „keine Probleme“: es wurden nur die neuesten "
                     f"{searched} von {total} Ereignissen im Fenster durchsucht.")
    elif total and searched < total:
        hints.append(f"Nur die neuesten {searched} von {total} Ereignissen geladen.")
    if hints:
        result["hinweis"] = " ".join(hints)
    while len(json.dumps(result, ensure_ascii=False)) > MAX_CHARS and result["ereignisse"]:
        result["ereignisse"].pop()
        result["treffer"] = len(result["ereignisse"])
        result["gekuerzt"] = True
    return _bounded(result)
