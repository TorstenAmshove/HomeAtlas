"""Reads the live nftables rule set of a host over SSH (Forced-Command), read-only (ADR-0017).

There is exactly ONE command, the constant `_NFT_COMMAND`. It carries no parameter and no setting
extends it. What really runs is decided by the target: the key of the dedicated user sits in
`authorized_keys` as ``restrict,from="<HomeAtlas-IP>",command="sudo /usr/sbin/nft -j list ruleset"``
and sudoers allows exactly that one command, so sshd runs it no matter what the client sends. This is
the first privilege change (`sudo`) on a read path: it is needed because only the live rule set shows
what applies (ADR-0017). The module is self-contained: it neither imports `probe_auth` (its
`_SSH_COMMANDS` stay untouched) nor any writing module (L6: duplicate the small SSH helper rather
than share it, as in `exposure_files.py`).

Opt-in per credential: accounts of category ``firewall_nftables`` with ``allowProbe`` and only while
``scanEnableFirewallNft`` is on (pipeline.py). `systemId` is the target host, `username`/`port` the SSH
user, the private key sits in `secretEnc`.

The parser keeps a positive list only: per base chain (a chain with a hook, families ``inet``/``ip``)
hook, priority, policy and its rules as normalised matches (``saddr``/``daddr``, ``dport``,
``ct_state``, ``iif``/``oif``) plus the verdict. Everything it cannot judge with certainty
(``jump``/``goto``, NAT, ``limit``, negation, ``meta l4proto``, unresolved sets, other families'
selectors, ...) becomes an ``unsupported`` reason on the rule; the evaluation then reports "unclear".
Comments, counters and raw JSON are never stored, shown or logged; error texts never contain output.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re

from . import crypto

_TIMEOUT = 20.0
# A full `nft -j` dump is larger than the config files `exposure_files` reads (256 KiB there).
_MAX_BYTES = 512 * 1024
_MAX_RULES = 500
_MAX_CHAINS = 100
_NFT_COMMAND = "nft -j list ruleset"
CATEGORY = "firewall_nftables"
SOURCE = "nftables"

_FAMILIES = ("inet", "ip")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CT_STATES = {"new", "established", "related", "invalid", "untracked"}
_IGNORED_EXPR = {"counter", "log", "comment"}  # no effect on the verdict


class NftError(ValueError):
    """The output is not a usable rule set."""


def _unsupported(reason: str, bucket: list[str]) -> None:
    if reason not in bucket:
        bucket.append(reason)


def _addr(value, bucket: list[str]) -> list[str]:
    """One match operand -> list of 'ip', 'a.b.c.d/n' or 'a-b' strings (IPv4 only)."""
    items = value["set"] if isinstance(value, dict) and "set" in value else [value]
    out: list[str] = []
    for item in items:
        try:
            if isinstance(item, dict) and "elem" in item:
                item = item["elem"].get("val") if isinstance(item["elem"], dict) else item["elem"]
            if isinstance(item, dict) and "prefix" in item:
                net = ipaddress.ip_network(f"{item['prefix']['addr']}/{item['prefix']['len']}", strict=False)
                out.append(str(net))
            elif isinstance(item, dict) and "range" in item:
                a, b = (ipaddress.ip_address(x) for x in item["range"])
                if a.version != 4 or b.version != 4:
                    raise ValueError
                out.append(f"{a}-{b}")
            elif isinstance(item, str):
                ip = ipaddress.ip_address(item)
                if ip.version != 4:
                    raise ValueError
                out.append(str(ip))
            else:
                raise ValueError
            if out and ":" in out[-1]:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            _unsupported("address", bucket)
            return []
    return out


def _ports(value, bucket: list[str]) -> list[str]:
    items = value["set"] if isinstance(value, dict) and "set" in value else [value]
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and "elem" in item:
            item = item["elem"].get("val") if isinstance(item["elem"], dict) else item["elem"]
        if isinstance(item, bool):
            _unsupported("port", bucket)
            return []
        if isinstance(item, int) and 0 < item < 65536:
            out.append(str(item))
        elif isinstance(item, dict) and "range" in item and len(item["range"]) == 2 \
                and all(isinstance(x, int) and 0 < x < 65536 for x in item["range"]):
            out.append(f"{item['range'][0]}-{item['range'][1]}")
        else:
            _unsupported("port", bucket)
            return []
    return out


def _resolve_set(value, family: str, table: str, sets: dict, bucket: list[str]):
    """'@name' -> the elements of a named set of the same table; anything else is returned as is."""
    if isinstance(value, str) and value.startswith("@"):
        elems = sets.get((family, table, value[1:]))
        if elems is None:
            _unsupported("set", bucket)
            return None
        return {"set": elems}
    return value


def _match(expr: dict, family: str, table: str, sets: dict, bucket: list[str]) -> dict | None:
    m = expr["match"]
    left, right, op = m.get("left"), m.get("right"), m.get("op")
    if op != "==":  # "!=", "<", "in", ... : negation and comparisons are not evaluated
        _unsupported("operator", bucket)
        return None
    right = _resolve_set(right, family, table, sets, bucket)
    if right is None:
        return None
    if isinstance(right, list):  # nft emits a bare list for e.g. `ct state { established, related }`
        right = {"set": right}
    if isinstance(left, dict) and "payload" in left:
        proto, field = left["payload"].get("protocol"), left["payload"].get("field")
        if proto == "ip" and field in ("saddr", "daddr"):
            values = _addr(right, bucket)
            return {"f": field, "v": values} if values else None
        if proto in ("tcp", "udp") and field == "dport":
            values = _ports(right, bucket)
            return {"f": "dport", "proto": proto, "v": values} if values else None
        _unsupported(f"{proto}.{field}"[:40], bucket)
        return None
    if isinstance(left, dict) and "ct" in left and left["ct"].get("key") == "state":
        states = right["set"] if isinstance(right, dict) and "set" in right else [right]
        if all(isinstance(s, str) and s in _CT_STATES for s in states):
            return {"f": "ct_state", "v": list(states)}
        _unsupported("ct", bucket)
        return None
    if isinstance(left, dict) and "meta" in left and left["meta"].get("key") in ("iifname", "oifname"):
        names = right["set"] if isinstance(right, dict) and "set" in right else [right]
        if all(isinstance(n, str) and _NAME.match(n) for n in names):
            return {"f": "iif" if left["meta"]["key"] == "iifname" else "oif", "v": list(names)}
        _unsupported("interface", bucket)
        return None
    _unsupported("match", bucket)
    return None


def _rule(raw: dict, number: int, family: str, table: str, sets: dict) -> dict:
    matches: list[dict] = []
    verdict = ""
    bad: list[str] = []
    for expr in raw.get("expr") or []:
        if not isinstance(expr, dict) or len(expr) != 1:
            _unsupported("expr", bad)
            continue
        kind = next(iter(expr))
        if kind in _IGNORED_EXPR:
            continue
        if kind == "match":
            try:
                parsed = _match(expr, family, table, sets, bad)
            except (AttributeError, KeyError, TypeError):
                parsed = None
                _unsupported("match", bad)
            if parsed:
                matches.append(parsed)
        elif kind in ("accept", "drop", "reject"):
            verdict = kind
        else:  # jump, goto, return, nat, limit, queue, ...
            _unsupported(re.sub(r"[^a-z0-9_]", "", str(kind).lower())[:20] or "expr", bad)
    return {"no": number, "verdict": verdict, "matches": matches[:12], "unsupported": bad[:6]}


def parse_ruleset(text: str, system_id: str = "") -> list[dict]:
    """-> `nft_host` fact plus one `nft_chain` fact per base chain. Raises `NftError` for unusable output."""
    try:
        doc = json.loads(text)
        items = doc["nftables"]
        if not isinstance(items, list):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise NftError("keine gültige nft-JSON-Ausgabe") from exc

    sets: dict[tuple, list] = {}
    chains: dict[tuple, dict] = {}
    ignored = 0
    rules_by_chain: dict[tuple, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if "set" in item and isinstance(item["set"], dict):
            s = item["set"]
            sets[(s.get("family"), s.get("table"), s.get("name"))] = list(s.get("elem") or [])
        elif "chain" in item and isinstance(item["chain"], dict):
            c = item["chain"]
            if c.get("family") in _FAMILIES and c.get("hook") in ("input", "output", "forward"):
                chains[(c["family"], c.get("table"), c.get("name"))] = c
            elif c.get("hook"):
                ignored += 1  # ip6 / bridge / arp / netdev base chains are not evaluated
        elif "rule" in item and isinstance(item["rule"], dict):
            r = item["rule"]
            rules_by_chain.setdefault((r.get("family"), r.get("table"), r.get("chain")), []).append(r)

    if len(chains) > _MAX_CHAINS or sum(len(rules_by_chain.get(k, [])) for k in chains) > _MAX_RULES:
        raise NftError("Regelsatz zu groß")

    facts: list[dict] = []
    total = 0
    for key, c in chains.items():
        family, table, name = key
        if not all(isinstance(x, str) and _NAME.match(x) for x in key):
            continue
        rules = [_rule(r, n, family, table, sets) for n, r in enumerate(rules_by_chain.get(key, []), 1)]
        total += len(rules)
        prio = c.get("prio")
        policy = c.get("policy") if c.get("policy") in ("accept", "drop") else ""
        facts.append({"kind": "nft_chain", "key": f"nft:{system_id}:{family}/{table}/{name}", "data": {
            "systemId": system_id, "family": family, "table": table, "chain": name, "hook": c["hook"],
            "prio": prio if isinstance(prio, int) else 0, "policy": policy, "rules": rules}})
    facts.insert(0, {"kind": "nft_host", "key": f"nft:{system_id}", "data": {
        "systemId": system_id, "chains": len(facts), "rules": total, "ignoredChains": ignored}})
    return facts


async def probe(host: str, account: dict) -> dict:
    """Returns {"ok", "error", "facts": [{kind, key, data}]}. One fixed command, see the module docstring."""
    if not host:
        return {"ok": False, "error": "Kein Zielsystem mit Adresse hinterlegt.", "facts": []}
    try:
        import asyncssh
    except ImportError:
        return {"ok": False, "error": "asyncssh ist nicht installiert.", "facts": []}

    secret = crypto.decrypt(account.get("secretEnc") or "")
    passphrase = crypto.decrypt(account.get("passphraseEnc") or "")
    port = int(account.get("port") or 0) or 22
    try:
        key = asyncssh.import_private_key(secret, passphrase or None)
    except (ValueError, KeyError):
        return {"ok": False, "error": "Der hinterlegte SSH-Schlüssel ließ sich nicht lesen.", "facts": []}
    try:
        async with asyncssh.connect(
            host=host, port=port, username=(account.get("username") or "").strip() or "homeatlas",
            client_keys=[key], password=None, known_hosts=None, connect_timeout=10,
        ) as connection:
            result = await asyncio.wait_for(
                connection.run(_NFT_COMMAND, check=False, input="", encoding="utf-8", errors="replace"),
                timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"SSH {host}:{port}: Zeitüberschreitung.", "facts": []}
    except Exception as exc:  # noqa: BLE001 -- asyncssh raises a wide family; never echo the message
        return {"ok": False, "error": f"SSH-Verbindung zu {host}:{port} fehlgeschlagen ({type(exc).__name__}).",
                "facts": []}
    text = str(result.stdout or "")
    if result.exit_status not in (0, None) or not text.strip():
        # sudo refused, nft missing or no output: unreadable, never "no rules"
        return {"ok": False, "error": f"nftables: Regelsatz auf {host} nicht lesbar (sudo/nft prüfen).", "facts": []}
    if len(text.encode("utf-8", "replace")) > _MAX_BYTES:
        return {"ok": False, "error": f"nftables: Regelsatz auf {host} ist zu groß.", "facts": []}
    try:
        facts = parse_ruleset(text, account.get("systemId") or "")
    except NftError as exc:
        return {"ok": False, "error": f"nftables: {exc} ({host}).", "facts": []}
    except Exception as exc:  # noqa: BLE001 -- a parser bug must not take the scan down or leak content
        return {"ok": False, "error": f"nftables: Ausgabe ließ sich nicht auswerten ({type(exc).__name__}).",
                "facts": []}
    return {"ok": True, "error": "", "facts": facts}
