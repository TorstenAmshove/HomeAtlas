"""Reads the cloudflared, Caddy and ddclient configuration of a system over SSH (Forced-Command).

Read-only (ADR-0014): per source type there is exactly ONE command, the constant in
`_FILE_COMMANDS`. It carries no path, no interpolation and no parameter, and no setting extends it.
Which file comes back is decided solely by the target system: the key of the dedicated user sits in
`authorized_keys` as `restrict,from="<HomeAtlas-IP>",command="cat <file>"`, so sshd runs that command
no matter what the client sends. `probe_auth._SSH_COMMANDS` is untouched and this module does not
import `probe_auth` (L6: duplicate rather than share).

Opt-in per credential like every other source: accounts of category `exposure_cloudflared`,
`exposure_caddy` or `exposure_ddclient` with `allowProbe` (pipeline.py), and only while
`scanEnableExposureFiles` is on. `systemId` is the target host, `username`/`port` the SSH user, the
private key sits in `secretEnc`.

The parsers keep only structured, non-secret fields (hostnames, targets, protocol/provider, mTLS yes/no).
Raw files are never stored, shown, logged or handed to a model; passwords, tokens, tunnel credentials
and everything else are discarded while parsing. That a tunnel token passes through memory for a moment
is accepted on purpose (ADR-0014). Error texts never contain file content.
"""
from __future__ import annotations

import asyncio
import re

from . import crypto

_TIMEOUT = 20.0
_MAX_BYTES = 256 * 1024
_MAX_FACTS = 500
_MAX_DEPTH = 8

# One fixed command per source type. The path is NOT part of it (see module docstring).
_FILE_COMMANDS = {
    "cloudflared": "cat",
    "caddy": "cat",
    "ddclient": "cat",
}
CATEGORIES = {
    "exposure_cloudflared": "cloudflared",
    "exposure_caddy": "caddy",
    "exposure_ddclient": "ddclient",
}

_HOST_RE = re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def _host(value: str) -> str:
    """A syntactically valid public hostname (lower-case) or ''. Anything else is dropped."""
    v = _SCHEME_RE.sub("", (value or "").strip().lower()).split("/", 1)[0].rsplit("@", 1)[-1]
    v = re.sub(r":\d+$", "", v).rstrip(".")
    return v[:253] if _HOST_RE.match(v) and len(v) <= 253 else ""


def _target(value: str) -> str:
    """An upstream/origin without credentials or path; placeholders and sockets are dropped."""
    v = (value or "").strip()
    if not v or "{" in v or v.startswith(("unix", "/", "@", "*")):
        return ""
    scheme = ""
    if _SCHEME_RE.match(v):
        scheme, v = v.split("://", 1)[0] + "://", v.split("://", 1)[1]
    v = scheme + v.rsplit("@", 1)[-1].split("/", 1)[0]
    return v[:200]


# ---------------------------------------------------------------------------------------------
# Caddyfile
# ---------------------------------------------------------------------------------------------

_CADDY_TOKEN = re.compile(r'#[^\n]*|"(?:[^"\\]|\\.)*"|`[^`]*`|\{[^\s{}]+\}|\n|[{}]|[^\s{}"`#]+')


def _caddy_tree(text: str) -> list[dict]:
    root: dict = {"args": [], "children": []}
    stack = [root]
    line: list[str] = []

    def flush():
        if line:
            stack[-1]["children"].append({"args": list(line), "children": []})
            line.clear()

    for tok in _CADDY_TOKEN.findall(text):
        if tok.startswith("#"):
            continue
        if tok == "\n":
            flush()
        elif tok == "{":
            node = {"args": list(line), "children": []}
            line.clear()
            stack[-1]["children"].append(node)
            stack.append(node)
        elif tok == "}":
            flush()
            if len(stack) > 1:
                stack.pop()
        else:
            line.append(tok.strip('"`') if tok[0] in "\"`" else tok)
    flush()
    return root["children"]


def _walk(nodes: list[dict], snippets: dict[str, list[dict]], depth: int = 0):
    for node in nodes:
        yield node
        args = node["args"]
        if args and args[0] == "import" and len(args) > 1 and depth < _MAX_DEPTH:
            yield from _walk(snippets.get(args[1], []), snippets, depth + 1)
        yield from _walk(node["children"], snippets, depth)


def parse_caddy(text: str) -> list[dict]:
    """-> `caddy_site` facts: {host, upstreams[], mtls, imports}. Imports of other files are not followed."""
    tree = _caddy_tree(text)
    snippets = {n["args"][0][1:-1]: n["children"] for n in tree
                if len(n["args"]) == 1 and n["args"][0].startswith("(") and n["args"][0].endswith(")")}
    facts: dict[str, dict] = {}
    for node in tree:
        args = node["args"]
        if not args or (args[0].startswith("(") and args[0].endswith(")")) or not node["children"]:
            continue  # global options block, snippet or a directive without block
        upstreams: list[str] = []
        mtls = False
        file_import = False
        for d in _walk(node["children"], snippets):
            da = d["args"]
            if not da:
                continue
            if da[0] == "client_auth":
                mtls = True
            elif da[0] == "reverse_proxy":
                for a in da[1:]:
                    t = _target(a)
                    if t and t not in upstreams:
                        upstreams.append(t)
            elif da[0] == "to":
                for a in da[1:]:
                    t = _target(a)
                    if t and t not in upstreams:
                        upstreams.append(t)
            elif da[0] == "import" and len(da) > 1 and da[1] not in snippets:
                file_import = True
        for address in " ".join(args).replace(",", " ").split():
            host = _host(address)
            if host and host not in facts:
                facts[host] = {"kind": "caddy_site", "key": host, "data": {
                    "host": host, "upstreams": upstreams[:10], "mtls": mtls, "imports": file_import}}
    return list(facts.values())[:_MAX_FACTS]


# ---------------------------------------------------------------------------------------------
# cloudflared config.yml (ingress only; credentials, token and tunnel id are never looked at)
# ---------------------------------------------------------------------------------------------

_KV = re.compile(r"^\s*(-\s+)?([A-Za-z]+)\s*:\s*(.*?)\s*$")


def _unquote(v: str) -> str:
    v = v.split(" #", 1)[0].strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def parse_cloudflared(text: str) -> list[dict]:
    """-> `tunnel_ingress` facts: {host, origin, tls_noverify}. The catch-all rule has no hostname."""
    entries: list[dict] = []
    in_ingress = False
    current: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.match(r"^\S", raw):  # a top-level key
            in_ingress = raw.startswith("ingress:")
            current = None
            continue
        if not in_ingress:
            continue
        m = _KV.match(raw)
        if not m:
            continue
        dash, key, value = m.group(1), m.group(2), _unquote(m.group(3))
        if dash and key in ("hostname", "service"):
            current = {"hostname": "", "service": "", "noTLSVerify": False}
            entries.append(current)
        if current is None:
            continue
        if key == "hostname":
            current["hostname"] = value
        elif key == "service":
            current["service"] = value
        elif key == "noTLSVerify":
            current["noTLSVerify"] = value.lower() == "true"
    facts: dict[str, dict] = {}
    for e in entries:
        host = _host(e["hostname"])
        service = e["service"]
        if not host or service.startswith("http_status:") or host in facts:
            continue
        facts[host] = {"kind": "tunnel_ingress", "key": host, "data": {
            "host": host, "origin": _target(service), "tls_noverify": e["noTLSVerify"]}}
    return list(facts.values())[:_MAX_FACTS]


# ---------------------------------------------------------------------------------------------
# ddclient.conf (protocol/server/use and the host names; login, password and zone are dropped)
# ---------------------------------------------------------------------------------------------

def parse_ddclient(text: str) -> list[dict]:
    """-> `ddns` facts: {client, provider, hosts[], ipv4, ipv6}."""
    joined = re.sub(r"\\\n", " ", text)
    blocks: list[dict] = []

    def new() -> dict:
        return {"protocol": "", "server": "", "hosts": [], "usev4": True, "usev6": False}

    cur = new()
    defaults = new()
    for raw in joined.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        for item in re.split(r"[,\s]+", line):
            if not item:
                continue
            if "=" in item:
                key, _, value = item.partition("=")
                key, value = key.strip().lower(), value.strip().strip("'\"")
                if key == "protocol":
                    if cur["hosts"]:
                        blocks.append(cur)
                        cur = {**new(), "server": defaults["server"], "usev4": defaults["usev4"],
                               "usev6": defaults["usev6"]}
                    cur["protocol"] = value.lower()[:40]
                elif key == "server":
                    cur["server"] = value.lower().split(":")[0][:100]
                elif key in ("usev4", "use"):
                    cur["usev4"] = value.lower() not in ("disabled", "no")
                elif key == "usev6":
                    cur["usev6"] = value.lower() not in ("disabled", "no")
                # login, password, zone, ssl, ... are deliberately ignored
            else:
                host = _host(item)
                if host and host not in cur["hosts"]:
                    cur["hosts"].append(host)
    if cur["hosts"]:
        blocks.append(cur)
    facts = []
    for i, b in enumerate(blocks[:_MAX_FACTS]):
        provider = b["protocol"] + (f" ({b['server']})" if b["server"] and b["protocol"] else b["server"])
        facts.append({"kind": "ddns", "key": f"ddclient:{i}", "data": {
            "client": "ddclient", "provider": provider[:120], "hosts": b["hosts"][:30],
            "ipv4": b["usev4"], "ipv6": b["usev6"]}})
    return facts


_PARSERS = {"cloudflared": parse_cloudflared, "caddy": parse_caddy, "ddclient": parse_ddclient}


# ---------------------------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------------------------

async def probe(source: str, host: str, account: dict, via: str = "") -> dict:
    """Returns {"ok", "error", "facts": [{kind, key, data}]}. `source` is a key of `_FILE_COMMANDS`."""
    command = _FILE_COMMANDS.get(source)
    if command is None:
        return {"ok": False, "error": "Unbekannter Quelltyp.", "facts": []}
    if not host:
        return {"ok": False, "error": "Kein Zielsystem mit Adresse hinterlegt.", "facts": []}
    try:
        import asyncssh
    except ImportError:
        return {"ok": False, "error": "asyncssh ist nicht installiert.", "facts": []}

    try:
        secret = crypto.decrypt_strict(account.get("secretEnc") or "")
        passphrase = crypto.decrypt_strict(account.get("passphraseEnc") or "")
    except crypto.SecretUnreadable:
        return {"ok": False, "error": "Secret nicht lesbar – Schlüsseldatei geändert?", "facts": []}
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
                connection.run(command, check=False, input="", encoding="utf-8", errors="replace"),
                timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"SSH {host}:{port}: Zeitüberschreitung.", "facts": []}
    except Exception as exc:  # noqa: BLE001 -- asyncssh raises a wide family; never echo the message
        return {"ok": False, "error": f"SSH-Verbindung zu {host}:{port} fehlgeschlagen ({type(exc).__name__}).",
                "facts": []}
    text = str(result.stdout or "")[:_MAX_BYTES]
    if not text.strip():
        return {"ok": False, "error": f"{source}: Die Datei auf {host} war leer oder nicht lesbar.", "facts": []}
    try:
        facts = _PARSERS[source](text)
    except Exception as exc:  # noqa: BLE001 -- a parser bug must not take the scan down or leak content
        return {"ok": False, "error": f"{source}: Datei ließ sich nicht auswerten ({type(exc).__name__}).",
                "facts": []}
    for fact in facts:
        if fact["kind"] != "cf_dns":
            fact["data"]["via"] = via
    return {"ok": True, "error": "", "facts": facts}
