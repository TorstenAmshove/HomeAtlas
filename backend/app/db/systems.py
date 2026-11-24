"""Persistence for systems (see db/__init__ for the package rules)."""
from __future__ import annotations

from .. import oui
from ._core import _JSON_COLUMNS, _conn, _dump, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Systems (the inventory)
# --------------------------------------------------------------------------------------------

_SYSTEM_FIELDS = (
    "kind", "name", "hostname", "ip", "mac", "vendor", "model", "os", "location", "purpose",
    "descriptionMd", "url", "docUrl", "docLink", "notes", "importance", "parentId", "status", "discovered",
    "confirmed", "discoverySource", "discoveryKey", "monitored", "monitorPorts",
    "openPorts", "services", "tags", "extra",
)


def list_systems(kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM systems"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY CASE importance WHEN 'critical' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, name COLLATE NOCASE"
    with _conn() as conn:
        return _rows(conn.execute(sql, params))


def get_system(system_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM systems WHERE id = ?", (system_id,)).fetchone())


def _has_address(system: dict) -> bool:
    return bool((system.get("ip") or "").strip() or (system.get("hostname") or "").strip())


def _enables_monitoring_on_critical(current: dict, patch: dict) -> bool:
    """True when this write is the transition "not critical -> critical" for a device with an address.

    "Critical implies monitored" is only a default applied once, at the moment of marking: later
    an admin may switch monitoring off and it stays off. A `monitored` value in the same write is
    explicit and always wins over the default, even when it equals the stored one -- the edit form
    sends only changed fields, plus `monitored` whenever the importance changes (deviceDraft.ts).
    """
    if patch.get("importance") != "critical" or current.get("importance") == "critical":
        return False
    if patch.get("monitored") is not None:
        return False
    return _has_address({**current, **patch})


def create_system(data: dict) -> dict:
    system_id = data.get("id") or _new_id()
    now = _now()
    values = {f: data.get(f) for f in _SYSTEM_FIELDS}
    if data.get("monitored") is None and _enables_monitoring_on_critical({}, data):
        values["monitored"] = 1
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO systems(id, {', '.join(_SYSTEM_FIELDS)}, firstSeen, lastSeen, updatedAt) "
            f"VALUES(?, {', '.join('?' * len(_SYSTEM_FIELDS))}, ?, ?, ?)",
            (system_id, *_system_params(values), data.get("firstSeen") or now, data.get("lastSeen") or now, now),
        )
    return get_system(system_id)  # type: ignore[return-value]


def _system_params(values: dict) -> list:
    defaults = {"kind": "other", "name": "Unbenannt", "importance": "normal", "status": "unknown"}
    out = []
    for field in _SYSTEM_FIELDS:
        value = values.get(field)
        if field in _JSON_COLUMNS:
            out.append(_dump(value))
        elif field == "parentId":
            out.append(value or None)
        elif field in ("discovered", "confirmed", "monitored"):
            out.append(1 if value else 0)
        else:
            out.append(defaults.get(field, "") if value in (None, "") else value)
    return out


def update_system(system_id: str, patch: dict) -> dict | None:
    current = get_system(system_id)
    if current is None:
        return None
    if _enables_monitoring_on_critical(current, patch):
        patch = {**patch, "monitored": 1}
    fields = [f for f in _SYSTEM_FIELDS if f in patch]
    if fields:
        merged = {**current, **patch}
        params = _system_params({f: merged.get(f) for f in _SYSTEM_FIELDS})
        by_field = dict(zip(_SYSTEM_FIELDS, params))
        assignments = ", ".join(f"{f} = ?" for f in fields)
        with _conn() as conn:
            conn.execute(
                f"UPDATE systems SET {assignments}, updatedAt = ? WHERE id = ?",
                (*[by_field[f] for f in fields], _now(), system_id),
            )
    if patch.get("lastSeen"):
        with _conn() as conn:
            conn.execute("UPDATE systems SET lastSeen = ? WHERE id = ?", (patch["lastSeen"], system_id))
    return get_system(system_id)


def set_parent_from_source(system_id: str, parent_id: str, source: str) -> dict | None:
    """Sets a controller-derived parent (unifi/proxmox) and records it in
    `extra.parentSource`. A parent a human set (`parentSource == "manual"`) is never touched."""
    current = get_system(system_id)
    if current is None:
        return None
    extra = current.get("extra") or {}
    if extra.get("parentSource") == "manual":
        return current
    return update_system(system_id, {"parentId": parent_id, "extra": {**extra, "parentSource": source}})


def delete_system(system_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE systems SET parentId = NULL WHERE parentId = ?", (system_id,))
        accounts_here = [row["id"] for row in conn.execute(
            "SELECT id FROM accounts WHERE systemId = ?", (system_id,),
        )]
        if accounts_here:
            placeholders = ",".join("?" * len(accounts_here))
            conn.execute(
                f"DELETE FROM accountAssignments WHERE accountId IN ({placeholders})",
                tuple(accounts_here),
            )
        conn.execute("DELETE FROM accountAssignments WHERE targetType = 'system' AND targetValue = ?",
                     (system_id,))
        conn.execute("DELETE FROM accounts WHERE systemId = ?", (system_id,))
        conn.execute("DELETE FROM systemAliases WHERE systemId = ?", (system_id,))
        conn.execute("DELETE FROM duplicateDismissals WHERE idA = ? OR idB = ?", (system_id, system_id))
        # History rows belong to the device; merge_systems repoints them, a delete drops them.
        for table in ("deviceConfigVersions", "deviceErrorEvents", "monitorEvents"):
            conn.execute(f"DELETE FROM {table} WHERE systemId = ?", (system_id,))
        conn.execute("DELETE FROM systems WHERE id = ?", (system_id,))


# `extra.interfaces` of a merged (multi-homed) system: {ip: {"openPorts", "services", "mac",
# "lastSeen"}}. Only rows that went through merge_systems carry it; the row's own
# openPorts/services are then the union over all its interfaces.
_INTERFACES_KEY = "interfaces"


def _interfaces_of(system: dict) -> dict:
    """The per-address port data of `system`: its stored `extra.interfaces`, or -- for a row that
    was never merged -- one entry for its own address built from its openPorts/services."""
    extra = system.get("extra") if isinstance(system.get("extra"), dict) else {}
    stored = extra.get(_INTERFACES_KEY)
    if isinstance(stored, dict) and stored:
        return {ip: dict(entry) for ip, entry in stored.items() if ip and isinstance(entry, dict)}
    ip = (system.get("ip") or "").strip()
    if not ip:
        return {}
    entry: dict = {"openPorts": system.get("openPorts") or [], "services": system.get("services") or []}
    if system.get("mac"):
        entry["mac"] = system["mac"]
    if system.get("lastSeen"):
        entry["lastSeen"] = system["lastSeen"]
    return {ip: entry}


def _union_interfaces(interfaces: dict) -> tuple[list, list]:
    ports: set[int] = set()
    services: dict = {}
    for entry in interfaces.values():
        for port in entry.get("openPorts") or ():
            if isinstance(port, int):
                ports.add(port)
        for service in entry.get("services") or ():
            if isinstance(service, dict) and isinstance(service.get("port"), int):
                services.setdefault(service["port"], service)
    return sorted(ports), [services[p] for p in sorted(services)]


def _combine_interfaces(keep: dict, remove: dict) -> dict:
    """`keep`'s entry wins per address, except that ports/services both rows saw on the same
    address are united (a hand-created row and the scanned row for the same IP)."""
    combined = {**remove, **keep}
    for ip in keep.keys() & remove.keys():
        ports, services = _union_interfaces({"a": keep[ip], "b": remove[ip]})
        combined[ip] = {**remove[ip], **keep[ip], "openPorts": ports, "services": services}
    return combined


def _merge_extra(keep_extra: object, remove_extra: object) -> dict:
    """`keep` wins per key; nested dicts (e.g. `probe`, keyed by probe target) are combined one
    level deep so both rows' entries survive."""
    keep_extra = keep_extra if isinstance(keep_extra, dict) else {}
    remove_extra = remove_extra if isinstance(remove_extra, dict) else {}
    merged = {**remove_extra, **keep_extra}
    for key, value in remove_extra.items():
        if key != _INTERFACES_KEY and isinstance(value, dict) and isinstance(keep_extra.get(key), dict):
            merged[key] = {**value, **keep_extra[key]}
    merged.pop(_INTERFACES_KEY, None)
    return merged


def _record_interface(existing: dict, seen_ip: str, previous_ip: str, via_alias: bool,
                      found: dict, now: str) -> dict:
    """Updates the entry for `seen_ip` in `existing`'s interfaces with what this finding saw. A
    finding without `openPorts` (UniFi, Proxmox -- sources that don't port-scan) leaves the
    entry's ports alone. `previous_ip` is the address this same interface had before (the alias's
    recorded IP before this scan, or the row's own IP); if it moved, its stale entry is dropped --
    unless another interface still has that address. Call after `_touch_alias_ip`."""
    interfaces = _interfaces_of(existing)
    if previous_ip and previous_ip != seen_ip:
        still_used = {a["ip"] for a in list_aliases(existing["id"])}
        if via_alias:
            still_used.add(existing.get("ip") or "")
        if previous_ip not in still_used:
            interfaces.pop(previous_ip, None)
    entry = dict(interfaces.get(seen_ip) or {})
    if found.get("openPorts") is not None:
        entry["openPorts"] = found.get("openPorts") or []
        entry["services"] = found.get("services") or []
    entry.setdefault("openPorts", [])
    entry.setdefault("services", [])
    if found.get("mac"):
        entry["mac"] = found["mac"]
    entry["lastSeen"] = now
    interfaces[seen_ip] = entry
    return interfaces


def merge_systems(keep_id: str, remove_id: str) -> dict | None:
    """Folds `remove_id` into `keep_id` as one physical device on record under two inventory rows
    -- the case this exists for is a multi-homed router discovered once per subnet interface (no
    shared MAC across interfaces for `upsert_discovered_system`'s own merge heuristics to catch,
    since each interface only speaks on its own subnet) plus, commonly, a further hand-created row
    for the same box. There is no automatic detection for this -- unlike upsert's MAC/Proxmox/
    IP+hostname fallbacks, "two rows are actually the same multi-homed device" has no reliable
    signal to key off of, so a human picks the pair and which one survives. Aliases keep the merge
    permanent: the removed row's discoveryKey and MAC (plus the IP seen under them) are stored in
    `systemAliases`, so a later scan finding them lands on `keep_id` instead of re-creating the
    duplicate. "No automatic detection" stays true -- only the human's pick ever merges.

    `keep_id` wins every field conflict; blank fields on it are filled from `remove_id` (same
    "new information, not an overwrite" rule as upsert_discovered_system's confirmed-row branch),
    and `remove_id`'s `confirmed`/`monitored` state is carried over if `keep_id` doesn't already
    have it, so a human-confirmed or monitored duplicate never silently loses that status to the
    row it's merged into. Every other table that points at `remove_id` by systemId is repointed to
    `keep_id` rather than dropped, so its accounts, config/error history and monitor events survive
    the merge instead of vanishing with the deleted row -- same manual-cleanup convention as
    delete_system above, since this codebase declares no FK constraints anywhere. Children of
    `remove_id` move to `keep_id`; if `keep_id` itself was a child of `remove_id` it takes over
    `remove_id`'s parent (or none), never itself.
    """
    if keep_id == remove_id:
        return get_system(keep_id)
    keep, remove = get_system(keep_id), get_system(remove_id)
    if keep is None or remove is None:
        return None

    # "ip" is included despite a multi-homed router having more than one real address -- an empty
    # `ip` on the surviving row would break everything keyed off it (monitoring, the SSH console,
    # the device list's address column), so the row still needs *a* reachable address even though
    # topology.py's Layer-3 view separately reads every interface address from its own probe data,
    # not this field.
    fill_fields = ("ip", "hostname", "mac", "vendor", "model", "os", "location", "purpose",
                   "descriptionMd", "url", "docUrl", "docLink", "notes")
    patch = {f: remove[f] for f in fill_fields if remove.get(f) and not keep.get(f)}
    # Discovered facts of the merged-away row (UniFi/mDNS/SSDP/probe data in `extra`, the open
    # ports and services seen on its address) are information about the same device, not a
    # conflicting value -- they are combined, with `keep` winning only where both say something.
    # Ports/services are kept per address in `extra.interfaces`, so a later scan can refresh one
    # interface without wiping what the others contributed (see `_record_interface`).
    interfaces = _combine_interfaces(_interfaces_of(keep), _interfaces_of(remove))
    extra = _merge_extra(keep.get("extra"), remove.get("extra"))
    if interfaces:
        extra[_INTERFACES_KEY] = interfaces
        patch["openPorts"], patch["services"] = _union_interfaces(interfaces)
    if extra:
        patch["extra"] = extra
    # Same "never overwritten once confirmed" rule as upsert_discovered_system -- importance is a
    # human classification, not a discovered fact, so it only carries over from the merged-away row
    # while `keep` hasn't been confirmed yet.
    if not keep.get("confirmed") and remove.get("importance") and remove.get("importance") != keep.get("importance"):
        patch["importance"] = remove["importance"]
    if remove.get("confirmed") and not keep.get("confirmed"):
        patch["confirmed"] = 1
    if remove.get("monitored") and not keep.get("monitored"):
        patch["monitored"] = 1
        patch["monitorPorts"] = remove.get("monitorPorts")
    if patch:
        update_system(keep_id, patch)

    with _conn() as conn:
        now = _now()
        keep_key = keep.get("discoveryKey") or ""
        keep_mac = (keep.get("mac") or "").lower()
        remove_mac = (remove.get("mac") or "").lower()
        remove_ip = remove.get("ip") or ""
        if remove_ip == (keep.get("ip") or ""):
            remove_ip = ""
        remove_key = remove.get("discoveryKey") or ""
        if remove_key and remove_key != keep_key:
            conn.execute(
                "INSERT OR REPLACE INTO systemAliases(aliasKey, systemId, ip, mac, createdAt) VALUES(?,?,?,?,?)",
                (remove_key, keep_id, remove_ip, remove_mac if remove_mac != keep_mac else "", now),
            )
        if remove_mac and remove_mac != keep_mac:
            conn.execute(
                "INSERT OR REPLACE INTO systemAliases(aliasKey, systemId, ip, mac, createdAt) VALUES(?,?,?,?,?)",
                (f"mac:{remove_mac}", keep_id, remove_ip, remove_mac, now),
            )
        conn.execute("UPDATE systemAliases SET systemId = ? WHERE systemId = ?", (keep_id, remove_id))
        if keep_key:
            conn.execute("DELETE FROM systemAliases WHERE aliasKey = ?", (keep_key,))
        if keep_mac:
            conn.execute("DELETE FROM systemAliases WHERE aliasKey = ?", (f"mac:{keep_mac}",))
        conn.execute("DELETE FROM duplicateDismissals WHERE idA = ? OR idB = ?", (remove_id, remove_id))
        # If `keep` was a child of `remove`, it inherits remove's parent (or none) -- repointing
        # it below would make it its own parent. Must run before the children are repointed.
        conn.execute("UPDATE systems SET parentId = ? WHERE id = ? AND parentId = ?",
                     (remove.get("parentId") or None, keep_id, remove_id))
        conn.execute("UPDATE systems SET parentId = ? WHERE parentId = ? AND id != ?",
                     (keep_id, remove_id, keep_id))
        conn.execute("UPDATE accounts SET systemId = ? WHERE systemId = ?", (keep_id, remove_id))
        conn.execute(
            "UPDATE accountAssignments SET targetValue = ? WHERE targetType = 'system' AND targetValue = ?",
            (keep_id, remove_id),
        )
        conn.execute("UPDATE monitorEvents SET systemId = ? WHERE systemId = ?", (keep_id, remove_id))
        conn.execute("UPDATE deviceConfigVersions SET systemId = ? WHERE systemId = ?", (keep_id, remove_id))
        conn.execute("UPDATE deviceErrorEvents SET systemId = ? WHERE systemId = ?", (keep_id, remove_id))
        conn.execute("DELETE FROM systems WHERE id = ?", (remove_id,))
    return get_system(keep_id)


def _self_reported_names(system: dict) -> set[str]:
    """UPnP friendlyName and mDNS names from `extra`; tolerant of missing/odd shapes."""
    extra = system.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    names: set[str] = set()
    ssdp = extra.get("ssdp")
    for entry in ssdp if isinstance(ssdp, list) else ():
        description = entry.get("description") if isinstance(entry, dict) else None
        name = description.get("friendlyName") if isinstance(description, dict) else None
        if isinstance(name, str) and name.strip():
            names.add(name.strip().lower())
    mdns = extra.get("mdns")
    for entry in mdns if isinstance(mdns, list) else ():
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.strip():
            names.add(name.strip().lower())
    return names


def _hostname_key(system: dict) -> str:
    host = (system.get("hostname") or "").strip().lower().split(".")[0]
    if not host or host.replace(".", "").isdigit():
        return ""
    return host


# A hostname or self-reported name carried by more rows than this is a generic default
# ("espressif", "android", "Sonos Speaker"), not evidence that the rows are one device.
_DUPLICATE_KEY_MAX_GROUP = 3


def find_duplicate_candidates() -> list[dict]:
    """Suggestions only -- nothing here ever merges. Pairs share a hostname (first DNS label) or a
    self-reported name. Vendor and model are deliberately not a reason: two identical devices
    (two identical access points, a pair of the same smart plugs) are the normal case in a home,
    not a duplicate, and flagging them buried the real hints. Keys shared by more than
    _DUPLICATE_KEY_MAX_GROUP rows are generic defaults and are skipped too. Grouped by key, so
    no O(n^2) comparison over all rows. Dismissed pairs are left out."""
    systems = list_systems()
    by_id = {s["id"]: s for s in systems}
    groups: dict[tuple[str, str], set[str]] = {}
    for system in systems:
        keys = []
        if _hostname_key(system):
            keys.append(("hostname", _hostname_key(system)))
        keys += [("selfName", n) for n in _self_reported_names(system)]
        for key in keys:
            groups.setdefault(key, set()).add(system["id"])
    pairs: dict[tuple[str, str], list[str]] = {}
    for (reason, _key), ids in groups.items():
        if len(ids) > _DUPLICATE_KEY_MAX_GROUP:
            continue
        ordered = sorted(ids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                reasons = pairs.setdefault((a, b), [])
                if reason not in reasons:
                    reasons.append(reason)
    with _conn() as conn:
        dismissed = {(r["idA"], r["idB"]) for r in conn.execute("SELECT idA, idB FROM duplicateDismissals")}
    return [
        {"aId": a, "bId": b, "aName": by_id[a]["name"], "bName": by_id[b]["name"], "reasons": reasons}
        for (a, b), reasons in sorted(pairs.items()) if (a, b) not in dismissed
    ]


def dismiss_duplicate(id_a: str, id_b: str) -> None:
    a, b = sorted((id_a, id_b))
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO duplicateDismissals(idA, idB, createdAt) VALUES(?,?,?)",
                     (a, b, _now()))


def list_aliases(system_id: str) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT aliasKey, ip, mac, createdAt FROM systemAliases WHERE systemId = ? ORDER BY createdAt, aliasKey",
            (system_id,),
        ))


def find_system_by_alias(alias_key: str) -> dict | None:
    if not alias_key:
        return None
    with _conn() as conn:
        return _row(conn.execute(
            "SELECT s.* FROM systemAliases a JOIN systems s ON s.id = a.systemId WHERE a.aliasKey = ?",
            (alias_key,),
        ).fetchone())


def _alias_ip(alias_key: str) -> str:
    with _conn() as conn:
        row = conn.execute("SELECT ip FROM systemAliases WHERE aliasKey = ?", (alias_key,)).fetchone()
    return (row["ip"] if row else "") or ""


def _touch_alias_ip(alias_key: str, ip: str) -> None:
    if not ip:
        return
    with _conn() as conn:
        conn.execute("UPDATE systemAliases SET ip = ? WHERE aliasKey = ?", (ip, alias_key))


def find_system_by_key(discovery_key: str) -> dict | None:
    if not discovery_key:
        return None
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM systems WHERE discoveryKey = ?", (discovery_key,)).fetchone())


def find_system_by_mac(mac: str) -> dict | None:
    """The strongest fallback identity there is: a MAC address is stable regardless of which
    source found the device (network sweep, Proxmox, ...) and regardless of what
    discoveryKey scheme that source happens to use. Needed because a device's *own* discoveryKey
    can legitimately change between scans for reasons that have nothing to do with the device
    changing -- see find_system_by_proxmox below for the concrete case this exists for."""
    mac = (mac or "").strip().lower()
    if not mac:
        return None
    with _conn() as conn:
        return _row(conn.execute(
            "SELECT * FROM systems WHERE mac = ? AND mac != '' LIMIT 1", (mac,)
        ).fetchone())


def find_system_by_proxmox(node: str, vmid: object) -> dict | None:
    """A guest's (node, vmid) pair, read from `extra.proxmox` -- Python-side, like pipeline.py's
    own `_assign_proxmox_parents`/`_link_unifi_topology`, since `extra` is opaque JSON to SQLite.

    This exists because proxmox_probe.probe's own discoveryKey is `mac:<mac>` when net0 parses a
    MAC and `proxmox:<node>:<kind>:<vmid>` when it doesn't (see its docstring) -- the *same* guest
    can flip between those two keys across scans (a NIC hot-added, a guest agent detail changes,
    net0's format varies) with nothing about the guest itself having changed. Without this, that
    flip reads as "new device" and duplicates the row instead of updating it.
    """
    if not node or vmid is None:
        return None
    for system in list_systems():
        proxmox = (system.get("extra") or {}).get("proxmox") or {}
        if proxmox.get("node") == node and proxmox.get("vmid") == vmid:
            return system
    return None


def find_system_by_ip_and_hostname(ip: str, hostname: str) -> dict | None:
    """Weak on their own (a DHCP lease can move an IP, a hostname can be reused), but together a
    reasonable fallback identity for a device recorded under one discoveryKey scheme by a human
    (a hand-created row with just an address and a hostname typed in) and found again under a
    different one by a later scan -- a phone rotating its privacy MAC being the common case."""
    ip, hostname = (ip or "").strip(), (hostname or "").strip()
    if not ip or not hostname:
        return None
    with _conn() as conn:
        return _row(conn.execute(
            "SELECT * FROM systems WHERE ip = ? AND hostname = ? AND ip != '' AND hostname != '' LIMIT 1",
            (ip, hostname),
        ).fetchone())


def find_system_by_ip(ip: str) -> dict | None:
    """The one non-container row with this IP, for the setup wizard's duplicate check. Returns None
    for an empty IP, no match, or an ambiguous match (several rows): guessing wrong would merge two
    devices. Containers/VMs/Docker rows share their host's IP, so they never count."""
    ip = (ip or "").strip()
    if not ip:
        return None
    with _conn() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM systems WHERE ip = ? AND kind NOT IN ('container', 'vm') "
            "AND COALESCE(discoverySource, '') != 'docker'", (ip,),
        ).fetchall())
    return rows[0] if len(rows) == 1 else None


def _has_controller_origin(system: dict) -> bool:
    # `extra.unifi`, not `discoverySource`: that one gets suffixes ("unifi+ki").
    extra = system.get("extra") or {}
    return "unifi" in extra


def find_system_by_unique_controller_ip(found: dict) -> dict | None:
    """Last-resort identity for routed devices: the network scan sees them by IP only (no ARP-
    resolved MAC off the local segment), the controller (UniFi) knows the same device by
    MAC -- and often no hostname matches. Pipeline order is scan first, controller second, so the
    rule works in both directions: at least one side must carry controller data.

    Deliberately conservative, since an IP is weak identity (DHCP moves it): exactly one existing
    row may hold the IP, and two rows with different non-empty MACs are different devices."""
    ip = (found.get("ip") or "").strip()
    if not ip:
        return None
    candidates = [s for s in list_systems() if (s.get("ip") or "").strip() == ip]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not (_has_controller_origin(candidate) or _has_controller_origin(found)):
        return None
    found_mac = (found.get("mac") or "").strip().lower()
    candidate_mac = (candidate.get("mac") or "").strip().lower()
    if found_mac and candidate_mac and found_mac != candidate_mac:
        return None
    return candidate


def find_system_for_merge(found: dict) -> dict | None:
    """Beyond `found`'s own exact discoveryKey (and its legacy keys, tried by the caller first),
    look for the same physical device under a different identity scheme entirely -- the case this
    exists for is a device one source only ever saw by IP (no ARP-resolved MAC, e.g. off the local
    L2 segment) that another source -- an API integration -- already knows by MAC, or a Proxmox
    guest whose discoveryKey scheme flipped (see find_system_by_proxmox). Priority order matches
    how trustworthy each identity is on its own: MAC first, then a Proxmox guest's own (node,
    vmid), then IP+hostname together, and finally a unique IP involving a controller row (see
    find_system_by_unique_controller_ip) as the weakest-but-still-useful fallback.
    """
    existing = find_system_by_mac(found.get("mac", ""))
    if existing is not None:
        return existing
    proxmox = (found.get("extra") or {}).get("proxmox") or {}
    existing = find_system_by_proxmox(proxmox.get("node", ""), proxmox.get("vmid"))
    if existing is not None:
        return existing
    existing = find_system_by_ip_and_hostname(found.get("ip", ""), found.get("hostname", ""))
    if existing is not None:
        return existing
    return find_system_by_unique_controller_ip(found)


def link_containers_to_host(host_ip: str) -> int:
    """Docker containers are discovered with the scanning host's own IP (see docker_probe.py) but
    no link to the system row that represents that host. Called once per scan to fill that in, so
    the network plan can nest a host's containers under it instead of showing a flat count with no
    owner. Never touches a parentId a human already set by hand."""
    if not host_ip:
        return 0
    with _conn() as conn:
        host = conn.execute(
            "SELECT id FROM systems WHERE ip = ? AND kind NOT IN ('container', 'vm') "
            "ORDER BY CASE kind WHEN 'server' THEN 0 WHEN 'nas' THEN 1 WHEN 'pc' THEN 2 ELSE 3 END LIMIT 1",
            (host_ip,),
        ).fetchone()
        if host is None:
            return 0
        cursor = conn.execute(
            "UPDATE systems SET parentId = ?, updatedAt = ? "
            "WHERE ip = ? AND discoverySource = 'docker' AND (parentId IS NULL OR parentId = '') AND id != ?",
            (host["id"], _now(), host_ip, host["id"]),
        )
        return cursor.rowcount


def find_existing_for_discovery(found: dict) -> tuple[dict | None, str]:
    """Read-only half of `upsert_discovered_system`: the row a finding would merge into, or None
    if the upsert would create a new one. Returns (row, via_alias) where `via_alias` is the alias
    key that matched ("" otherwise). Order: exact key, legacy keys, alias, `find_system_for_merge`.
    The pipeline uses it to tell new findings (worth an LLM call) from known ones.
    """
    found_key = found.get("discoveryKey", "")
    existing = find_system_by_key(found_key)
    if existing is None:
        for legacy_key in found.get("legacyDiscoveryKeys") or ():
            existing = find_system_by_key(legacy_key)
            if existing is not None:
                break
    if existing is None:
        found_mac = (found.get("mac") or "").strip().lower()
        for candidate in (found_key, *(found.get("legacyDiscoveryKeys") or ()),
                          f"mac:{found_mac}" if found_mac else ""):
            existing = find_system_by_alias(candidate)
            if existing is not None:
                return existing, candidate
    if existing is None:
        existing = find_system_for_merge(found)
    return existing, ""


def upsert_discovered_system(found: dict) -> tuple[dict, bool]:
    """Merges one discovery result into the inventory, keyed on `discoveryKey`. Returns
    (system, created).

    Fields the user has edited by hand are never overwritten: once a row is `confirmed`, discovery
    may only refresh the volatile facts (ip, status, ports, evidence) -- otherwise every rescan
    would wipe the human-written `name`, `location` and `descriptionMd`, which is the actual value
    the app accumulates over time.

    `legacyDiscoveryKeys`, if present, is a list of discoveryKey values a prober used to emit for
    this same device before its key scheme changed (see docker_probe.py's compose-based key). It
    is only ever a lookup fallback -- never written to the row -- so that an installation upgrading
    across the scheme change merges into its existing row instead of duplicating it.

    `importance` follows the same rule as every other human-editable field below -- once a row is
    `confirmed`, discovery/classification/Proxmox tags may no longer touch it, in either direction.
    The classification is the user's call to make and keep; the app only ever proposes a default
    for new or not-yet-confirmed rows.

    Beyond the exact-key (and legacy-key) lookups below, `find_system_for_merge` tries the same
    device under a different identity scheme entirely -- MAC, then Proxmox (node, vmid), then
    IP+hostname, then a unique IP shared with a controller (UniFi) row, in that priority
    order -- so a device found this scan via one source (say, an ARP
    sweep, with no resolved MAC) merges into the row an earlier scan already created via another
    (say, Proxmox, keyed by MAC) instead of duplicating it. See its own docstring for why each
    fallback exists.

    Between the exact/legacy-key lookups and `find_system_for_merge` sits the alias lookup: keys
    (and `mac:<mac>`) of rows a human merged away are attributed to the surviving row. On such a
    hit the survivor's own discoveryKey/ip/mac stay untouched (the alias row records the IP seen),
    and the finding's ports/services land in that address's `extra.interfaces` entry rather than
    replacing the other interfaces' (see `_record_interface`). A finding with no `openPorts` at all
    (a controller or Proxmox source) never touches the stored ports.
    """
    existing, via_alias = find_existing_for_discovery(found)
    now = _now()
    seen_ip = (found.get("ip") or "").strip()
    seen_mac = found.get("mac") or ""
    previous_ip = (existing.get("ip") or "") if existing is not None else ""
    if via_alias:
        previous_ip = _alias_ip(via_alias)
        _touch_alias_ip(via_alias, seen_ip)
        found = {k: v for k, v in found.items() if k not in ("discoveryKey", "ip", "mac")}
    if existing is None:
        created = create_system({**found, "discovered": 1, "firstSeen": now, "lastSeen": now})
        return created, True

    found_extra = found.get("extra") or {}
    existing_extra = existing.get("extra") or {}
    # The UniFi controller is the source of truth for its assigned device and client names. A
    # non-UniFi finding must not replace one, but a later UniFi scan may update it.
    unifi = found_extra["unifi"] if "unifi" in found_extra else existing_extra.get("unifi") or {}
    unifi_name = oui.real_name(unifi.get("name"))
    volatile = {
        "ip": found.get("ip") or existing["ip"],
        "status": found.get("status") or "online",
        "extra": {**existing_extra, **found_extra},
        "lastSeen": now,
        "discoveryKey": found.get("discoveryKey") or existing["discoveryKey"],
    }
    # Sources that don't port-scan (UniFi, Proxmox) send no openPorts at all -- that is
    # "unknown", not "none open", so it must not wipe what the network scan found.
    if found.get("openPorts") is not None:
        volatile["openPorts"] = found.get("openPorts")
        volatile["services"] = found.get("services")
    if seen_ip and (via_alias or isinstance(existing_extra.get(_INTERFACES_KEY), dict)):
        interfaces = _record_interface(existing, seen_ip, previous_ip, bool(via_alias),
                                       {**found, "mac": seen_mac}, now)
        volatile["extra"][_INTERFACES_KEY] = interfaces
        volatile["openPorts"], volatile["services"] = _union_interfaces(interfaces)
    if not found.get("mac") and existing.get("mac") and existing["discoveryKey"].startswith("mac:"):
        # An IP-only finding merged into a MAC-keyed row must not flip its key back and forth
        # between scan and controller on every run.
        volatile["discoveryKey"] = existing["discoveryKey"]
    if not existing["confirmed"]:
        # The LLM classification runs once, when a device first appears (classify.apply sets
        # `extra.aiConfidence`). Rule-based values of a later scan must not wipe that result;
        # only names/kinds a source supplies (or a device reports itself) still win.
        ai_protected: set[str] = set()
        if existing_extra.get("aiConfidence"):
            ai_protected = {"vendor", "model", "purpose", "descriptionMd", "docUrl", "importance"}
            tokens = set((found.get("discoverySource") or "").split("+"))
            names = {"docker", "proxmox", "unifi"}
            if not (tokens & names or any(key in found_extra for key in names)):
                ai_protected.add("kind")
                if found_extra.get("nameSource") not in ("upnp", "mdns", "shelly"):
                    ai_protected.add("name")
        # A MAC or a UniFi fallback is only a stand-in: it fills a row that has no real name yet
        # (or replaces a stored MAC), but never displaces a name another source supplied.
        found_unifi = found_extra.get("unifi") or {}
        found_is_stand_in = not oui.real_name(found.get("name")) or (
            "name" in found_unifi and not oui.real_name(found_unifi["name"]))
        if found_is_stand_in and oui.real_name(existing.get("name")):
            ai_protected.add("name")
        for field in ("kind", "name", "hostname", "mac", "vendor", "model", "os", "location",
                      "purpose", "descriptionMd", "url", "docUrl", "docLink", "importance"):
            value = found.get(field)
            if value and field not in ai_protected:
                volatile[field] = value
        if unifi_name:
            volatile["name"] = unifi_name
    else:
        # Even for confirmed rows, fill fields that are still empty -- adding a MAC, a vendor or a
        # manufacturer manual to a hand-created entry is strictly new information, not an
        # overwrite. `purpose` and `location` are included because a hand-created row usually has
        # only a name, and filling the blanks is the whole point of a rescan.
        for field in ("hostname", "mac", "vendor", "model", "os", "docUrl", "docLink", "purpose", "location"):
            if found.get(field) and not existing.get(field):
                volatile[field] = found[field]
    return update_system(existing["id"], volatile), False  # type: ignore[return-value]


def mark_systems_offline(seen_ids: set[str], skip_sources: frozenset[str] | set[str] = frozenset()) -> None:
    """Everything previously discovered but absent from this scan goes to `offline` -- manually
    created (non-discovered) entries are left alone, since "I documented my heat pump" says
    nothing about whether it answers pings.

    `skip_sources` names sources that were switched off or could not be read this scan: a device
    whose `discoverySource` (tokens joined by "+") contains one of them keeps its status, because
    "the source delivered nothing" is not "the device is gone" (#139)."""
    with _conn() as conn:
        rows = conn.execute("SELECT id, discoverySource FROM systems WHERE discovered = 1").fetchall()
        stale = [r["id"] for r in rows
                 if r["id"] not in seen_ids
                 and not skip_sources.intersection((r["discoverySource"] or "").split("+"))]
        for i in range(0, len(stale), 500):
            chunk = stale[i:i + 500]
            conn.execute(
                f"UPDATE systems SET status = 'offline' WHERE id IN ({','.join('?' * len(chunk))})",
                tuple(chunk),
            )
