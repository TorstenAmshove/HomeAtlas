"""Basis-Übersichtsplan des Heimnetzes als SVG.

Rendered server-side rather than with a diagram library in the browser: the layout is a fixed set
of layers (Internet → Router → Verteilung → Server → Endgeräte), so a general-purpose graph engine
would add a megabyte of JavaScript to draw something this file can place deterministically.

Readability decisions, since this is meant for someone who does not read network diagrams:

* Individually named boxes only where the name matters -- router, switches/APs, servers, NAS.
  Everything else is grouped and counted ("14 Computer & Mobilgeräte"), because forty labelled
  boxes is a picture nobody looks at twice.
* Containers are drawn inside their host, not as peers, which is where they actually live.
* Colour carries status (reachable / not reachable), and is never the only signal -- every device
  box also says so in words ("erreichbar" / "nicht erreichbar" / "unbekannt"), and both plans carry
  the same legend.
* A box is never narrower than `_MIN_BOX_W`; a row with more boxes widens the canvas (viewBox)
  instead of squeezing them further.
"""
from __future__ import annotations

import html
import ipaddress
import re
from datetime import datetime, timedelta, timezone

from . import db

_W = 1000
_BOX_H = 64
_GAP_X = 16
_LAYER_GAP = 90
_MIN_BOX_W = 90
# Caps per row. Devices beyond them are not drawn; PlanPage.tsx lists everything the SVG does not
# contain ("Nicht im Plan gezeichnet"), so nothing disappears.
_MAX_ROUTERS = 6
_MAX_NETWORK = 10
_MAX_CRITICAL_BOXES = 10

_COLORS = {
    "bg": "#0b1120",
    "box": "#131c31",
    "boxAlt": "#1b2540",
    "border": "#26304a",
    "text": "#e8edf7",
    "muted": "#94a3b8",
    "line": "#3b4767",
    "ok": "#34d399",
    "down": "#f87171",
    "accent": "#38bdf8",
}

def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


_STATUS_WORD = {"online": "erreichbar", "offline": "nicht erreichbar"}


def _canvas_width(max_items: int) -> int:
    """Canvas width that keeps `max_items` boxes in one row at least `_MIN_BOX_W` wide."""
    return max(_W, 80 + max_items * _MIN_BOX_W + max(0, max_items - 1) * _GAP_X)


def _box(x: float, y: float, w: float, h: float, title: str, subtitle: str = "",
         status: str = "", fill: str | None = None, system_id: str | None = None,
         expandable: bool = False, show_status: bool = False) -> str:
    accent = _COLORS["ok"] if status == "online" else _COLORS["down"] if status == "offline" else _COLORS["border"]
    chars = max(6, int(w / 7.2))
    if show_status:
        title_y = y + (20 if subtitle else 26)
    else:
        title_y = y + (20 if subtitle else h / 2 + 4)
    parts = [
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="10" '
        f'fill="{fill or _COLORS["box"]}" stroke="{accent}" stroke-width="1.5"/>',
        f'<text x="{x + w / 2:.0f}" y="{title_y:.0f}" text-anchor="middle" '
        f'fill="{_COLORS["text"]}" font-size="13" font-weight="600">{_esc(_truncate(title, chars))}</text>',
    ]
    if show_status:
        word = _STATUS_WORD.get(status, "unbekannt")
        color = accent if status in _STATUS_WORD else _COLORS["muted"]
        parts.append(
            f'<text x="{x + w / 2:.0f}" y="{y + (54 if subtitle else 48):.0f}" text-anchor="middle" '
            f'fill="{color}" font-size="11">● {word}</text>'
        )
    if subtitle:
        parts.append(
            f'<text x="{x + w / 2:.0f}" y="{y + 37:.0f}" text-anchor="middle" '
            f'fill="{_COLORS["muted"]}" font-size="11">{_esc(_truncate(subtitle, chars + 4))}</text>'
        )
    body = "".join(parts)
    if not system_id:
        return body
    # Every named box links straight to its device page -- an expandable one (a host with
    # containers/VMs nested in it) is additionally marked `data-expand` so the frontend opens the
    # filtered device list instead, since that box represents several systems, not just itself.
    # The plan stays a single static SVG either way (see module docstring) and never re-lays-out
    # on click; the frontend does the navigating.
    attrs = f'data-system-id="{_esc(system_id)}" style="cursor:pointer"'
    if expandable:
        attrs += ' data-expand="1"'
    return f'<g {attrs}>{body}</g>'


def _row(items: list[dict], y: float, box_w_max: float = 200,
         width: int = _W) -> tuple[str, list[tuple[float, float]]]:
    """Lays out one centred row. Returns (svg, [(centre_x, y) …]) so the caller can draw edges.
    Boxes shrink to fit `width` but never below `_MIN_BOX_W` (the caller widens the canvas via
    `_canvas_width`). An item with `link: False` is drawn but not clickable; an item with a
    `status` key gets the status word."""
    if not items:
        return "", []
    count = len(items)
    box_w = max(_MIN_BOX_W, min(box_w_max, (width - 80 - _GAP_X * (count - 1)) / count))
    total = count * box_w + _GAP_X * (count - 1)
    start = (width - total) / 2
    svg, anchors = [], []
    for index, item in enumerate(items):
        x = start + index * (box_w + _GAP_X)
        svg.append(_box(x, y, box_w, _BOX_H, item["title"], item.get("subtitle", ""),
                        item.get("status") or "", item.get("fill"),
                        item.get("id") if item.get("link", True) else None,
                        item.get("expand", False), show_status="status" in item))
        anchors.append((x + box_w / 2, y))
    return "".join(svg), anchors


def _chain_layers(items: list[dict]) -> list[list[dict]]:
    """Groups items into generations by `parentId` within the same list -- e.g. a secondary
    router (UCG) plugged into the primary one (FritzBox) renders one row below it instead of
    beside it, matching how the household actually wired it rather than a flat guess."""
    ids = {i["id"] for i in items}
    by_parent: dict[str | None, list[dict]] = {}
    for item in items:
        parent = item.get("parentId") if item.get("parentId") in ids else None
        by_parent.setdefault(parent, []).append(item)
    layers: list[list[dict]] = []
    frontier = by_parent.get(None, [])
    placed: set[str] = set()
    while frontier:
        layers.append(frontier)
        placed.update(i["id"] for i in frontier)
        frontier = [child for parent in frontier for child in by_parent.get(parent["id"], [])]
    # Anything left over is an orphaned chain (e.g. a parentId cycle from bad data) -- still show
    # it rather than silently dropping a device from the plan.
    leftover = [i for i in items if i["id"] not in placed]
    if leftover:
        layers.append(leftover)
    return layers


def _edges_by_parent(anchor_by_id: dict[str, tuple[float, float]], layer: list[dict],
                     anchors: list[tuple[float, float]], fallback_top: tuple[float, float]) -> str:
    """Like `_edges`, but each item connects to its own parent's anchor (falling back to
    `fallback_top` for items with no parent in this diagram) instead of one shared trunk.

    `anchors` must be `layer`'s own just-computed anchors (parallel by index, straight from
    `_row()`) -- NOT looked up via `anchor_by_id`, because the caller adds this row's own ids to
    `anchor_by_id` only *after* drawing it (same order the router-chain loop already used), so at
    call time `anchor_by_id` never contains them yet. Looking them up there instead of taking them
    as a parameter silently produced empty edge lists -- boxes drew, connecting lines did not."""
    groups: dict[str, list[tuple[float, float]]] = {}
    for item, anchor in zip(layer, anchors):
        key = item.get("parentId") if item.get("parentId") in anchor_by_id else "__root__"
        groups.setdefault(key, []).append(anchor)
    svg = []
    for key, bottoms in groups.items():
        top = anchor_by_id.get(key, fallback_top)
        svg.append(_edges(top, bottoms))
    return "".join(svg)


def _edges(top: tuple[float, float], bottoms: list[tuple[float, float]]) -> str:
    """Orthogonal connectors from one box's bottom edge to the top edge of each box below."""
    if not bottoms:
        return ""
    top_x, top_y = top
    mid_y = top_y + _BOX_H + (_LAYER_GAP - _BOX_H) / 2
    paths = [f'<path d="M {top_x:.0f} {top_y + _BOX_H:.0f} V {mid_y:.0f}" '
             f'stroke="{_COLORS["line"]}" stroke-width="1.5" fill="none"/>']
    xs = [x for x, _ in bottoms]
    if len(xs) > 1:
        paths.append(f'<path d="M {min(xs):.0f} {mid_y:.0f} H {max(xs):.0f}" '
                     f'stroke="{_COLORS["line"]}" stroke-width="1.5" fill="none"/>')
    for x, y in bottoms:
        paths.append(f'<path d="M {x:.0f} {mid_y:.0f} V {y:.0f}" '
                     f'stroke="{_COLORS["line"]}" stroke-width="1.5" fill="none"/>')
    return "".join(paths)


def _label(x: float, y: float, text: str) -> str:
    return (f'<text x="{x:.0f}" y="{y:.0f}" fill="{_COLORS["muted"]}" font-size="11" '
            f'letter-spacing="0.08em" font-weight="700">{_esc(text.upper())}</text>')


def _legend(height: float) -> str:
    legend_y = height - 26
    return (
        f'<circle cx="44" cy="{legend_y - 4:.0f}" r="5" fill="{_COLORS["ok"]}"/>'
        f'<text x="56" y="{legend_y:.0f}" fill="{_COLORS["muted"]}" font-size="11">erreichbar</text>'
        f'<circle cx="150" cy="{legend_y - 4:.0f}" r="5" fill="{_COLORS["down"]}"/>'
        f'<text x="162" y="{legend_y:.0f}" fill="{_COLORS["muted"]}" font-size="11">nicht erreichbar</text>'
    )


def _midpoint(anchors: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(x for x, _ in anchors) / len(anchors), anchors[0][1])


def render(settings: dict | None = None) -> str:
    settings = settings or db.get_settings()
    systems = db.list_systems()
    by_kind: dict[str, list[dict]] = {}
    for system in systems:
        by_kind.setdefault(system["kind"], []).append(system)

    routers = by_kind.get("router", [])
    network = by_kind.get("network", [])
    # Routers carry no uplink of their own (no source sets a router's parentId), so a cascade is
    # inferred from subnets exactly like in the Layer-3 plan; a manual parent on a router still wins.
    router_parents = _router_parents(routers)
    drawn_routers = [{**r, "parentId": router_parents.get(r["id"])} for r in routers[:_MAX_ROUTERS]]
    drawn_network = network[:_MAX_NETWORK]
    backbone_ids = {r["id"] for r in drawn_routers} | {n["id"] for n in drawn_network}
    # A critical router/switch is already drawn in its backbone row; only the rest gets a box in
    # "Wichtige Geräte" (including a critical router/switch the backbone cap cut off). The cap is
    # applied after that filter so nothing drawn twice and nothing silently lost to the wrong list.
    critical_all = [s for s in systems if s.get("importance") == "critical"]
    critical_ids = {s["id"] for s in critical_all}
    critical = [s for s in critical_all if s["id"] not in backbone_ids][:_MAX_CRITICAL_BOXES]
    width = _canvas_width(max(
        [len(layer) for layer in _chain_layers(drawn_routers)]
        + [len(layer) for layer in _chain_layers(drawn_network)]
        + [len(critical), 1]
    ))

    svg: list[str] = []
    y = 40
    # Anchors of every backbone/important box placed so far, kept across layers (not reset per
    # section) so a later "Wichtige Geräte" row can point a parentId edge at a specific
    # router or switch instead of only the generic trunk below it.
    anchor_by_id: dict[str, tuple[float, float]] = {}

    # --- Internet -----------------------------------------------------------------------
    svg.append(_label(40, y - 12, "Internet"))
    internet_svg, internet_anchor = _row([{
        "title": "Internet",
        "subtitle": settings.get("homeName") and f"Zugang für {settings['homeName']}" or "",
        "fill": _COLORS["boxAlt"],
    }], y, box_w_max=220, width=width)
    svg.append(internet_svg)
    previous = internet_anchor[0]
    y += _LAYER_GAP

    # --- Router, chained by parentId (Internet -> FritzBox -> UCG -> …) ------------
    if routers:
        svg.append(_label(40, y - 12, "Router"))
        leaf_anchors: list[tuple[float, float]] = []
        for depth, layer in enumerate(_chain_layers(drawn_routers)):
            items = [{"id": r["id"], "title": r["name"], "subtitle": r["ip"], "status": r["status"]}
                     for r in layer]
            row_svg, anchors = _row(items, y, box_w_max=260, width=width)
            svg.append(_edges(previous, anchors) if depth == 0
                      else _edges_by_parent(anchor_by_id, layer, anchors, previous))
            svg.append(row_svg)
            anchor_by_id.update(zip((r["id"] for r in layer), anchors))
            leaf_anchors = anchors
            y += _LAYER_GAP
        previous = _midpoint(leaf_anchors)

    # --- Verteilung -----------------------------------------------------------------------
    # Chained by parentId, same as the router section above -- a UniFi AP's parentId (set by
    # pipeline.py's _link_unifi_topology from the controller's own uplink info) places it under
    # the switch it is actually plugged into instead of beside it in an unordered row. A device
    # with no resolved uplink (no UniFi credential, or the field wasn't present in the API
    # response) still renders -- `_chain_layers` treats an unresolved parentId as root, same
    # degrade-gracefully posture as the parentId links in "Wichtige Geräte" below.
    if network:
        svg.append(_label(40, y - 12, "Verteilung (Switche, WLAN)"))
        leaf_anchors: list[tuple[float, float]] = []
        for depth, layer in enumerate(_chain_layers(drawn_network)):
            items = [{"id": n["id"], "parentId": n.get("parentId"), "title": n["name"],
                     "subtitle": n["ip"], "status": n["status"]} for n in layer]
            row_svg, anchors = _row(items, y, width=width)
            svg.append(_edges(previous, anchors) if depth == 0
                      else _edges_by_parent(anchor_by_id, layer, anchors, previous))
            svg.append(row_svg)
            anchor_by_id.update(zip((n["id"] for n in layer), anchors))
            leaf_anchors = anchors
            y += _LAYER_GAP
        previous = _midpoint(leaf_anchors)

    # --- Wichtige Geräte: alles mit Bedeutung "kritisch" ---------------------------------
    # Everything else (including non-critical servers/NAS and all end devices) lives in the
    # collapsible, kind-grouped lists PlanPage.tsx renders below the plan -- this file only ever
    # draws what someone marked as mattering, plus the backbone that carries it. A critical
    # container/VM used to be excluded here and only ever showed up folded into its host's
    # collapsed "N Container/VM" count -- exactly the kind of thing marking it critical was
    # supposed to prevent -- so it now gets its own box here like any other critical device.
    host_ids = {s["id"] for s in systems if s["kind"] not in ("container", "vm")}
    children_by_host: dict[str, list[dict]] = {}
    for kind in ("container", "vm"):
        for s in by_kind.get(kind, []):
            if s["id"] in critical_ids:
                continue  # drawn on its own below instead of folded into the host's summary count
            parent = s.get("parentId")
            if parent in host_ids:
                children_by_host.setdefault(parent, []).append(s)

    if critical:
        svg.append(_label(40, y - 12, "Wichtige Geräte"))
        # Lines come from `parentId` only (UniFi uplink, Proxmox/Docker host); a device whose
        # parent isn't anchored above (router/switch) falls back to the plain trunk connection below.
        items = []
        for s in critical:
            subtitle = s["ip"]
            expand = False
            if s["id"] in host_ids:
                children = children_by_host.get(s["id"], [])
                if children:
                    running = sum(1 for c in children if c["status"] == "online")
                    subtitle = f'{s["ip"]} · {len(children)} Container/VM, {running} aktiv ▸'
                    expand = True
            # A device's parentId (UniFi uplink, or the Proxmox/Docker host a container/VM was
            # found on, set by pipeline.py) names what it hangs off directly.
            resolved_parent = s.get("parentId") if s.get("parentId") in anchor_by_id else None
            items.append({"id": s["id"], "parentId": resolved_parent, "title": s["name"],
                         "subtitle": subtitle, "status": s["status"], "expand": expand})
        row_svg, anchors = _row(items, y, width=width)
        svg.append(_edges_by_parent(anchor_by_id, items, anchors, previous))
        svg.append(row_svg)
        anchor_by_id.update(zip((s["id"] for s in critical), anchors))
        y += _LAYER_GAP

    if len(systems) == 0:
        svg.append(
            f'<text x="{width / 2:.0f}" y="{y:.0f}" text-anchor="middle" fill="{_COLORS["muted"]}" '
            f'font-size="14">Noch keine Geräte erfasst — ein Netzwerk-Scan füllt diesen Plan.</text>'
        )
        y += 40

    height = y + 20
    legend = _legend(height)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" '
        f'width="100%" role="img" aria-label="Übersichtsplan des Heimnetzes" '
        f'font-family="Segoe UI, system-ui, sans-serif">'
        f'<rect width="{width}" height="{height:.0f}" fill="{_COLORS["bg"]}"/>'
        f'{"".join(svg)}{legend}</svg>'
    )


def _subnet_of(ip: str) -> str:
    parts = ip.split(".")
    return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 and all(p.isdigit() for p in parts) else "unbekanntes Netz"


def _subnet_sort_key(subnet: str) -> tuple:
    """Numeric order (10.0.0.0/24 before 192.168.2.0/24 before 192.168.10.0/24), shorter prefix
    first on the same address, "unbekanntes Netz" last. Same tuple shape for every input so keys
    always compare."""
    if subnet == "unbekanntes Netz":
        return (1, (), 0)
    address, _, prefix = subnet.partition("/")
    return (0, tuple(int(p) for p in address.split(".")), int(prefix) if prefix.isdigit() else 0)


# Any dotted-quad that is itself a plausible subnet mask (255.255.255.0, 255.255.0.0, ...) rather
# than a host address -- some interface listings print masks
# right next to the address they belong to, and this keeps them out of `_router_subnets` below.
_MASK_OCTETS = {"0", "128", "192", "224", "240", "248", "252", "254", "255"}
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _looks_like_mask(ip: str) -> bool:
    """A real subnet mask is a contiguous run of 1-bits followed by 0-bits (255.255.255.0,
    255.255.0.0, ...) -- checking each octet is individually a valid mask byte isn't enough, since
    e.g. 224.0.0.128 or 128.192.240.0 pass that test octet-by-octet while being ordinary host
    addresses, not masks."""
    parts = ip.split(".")
    if not all(p in _MASK_OCTETS for p in parts):
        return False
    bits = "".join(f"{int(p):08b}" for p in parts)
    return "01" not in bits


def _router_subnets(system: dict) -> set[str]:
    """Every /24 this router has an interface address in, read from the Linux "ip" fact
    probe_auth.py collected for a Linux-based router/gateway -- a coarse regex scan rather than a
    strict parser, since all that matters here is which subnets touch this router.

    Falls back to the subnet implied by the router's own single stored `ip` when no such fact
    exists (an unprobed router, or one behind a credential without allowProbe) -- a single-homed
    guess is still better than dropping the router from the Layer-3 plan entirely.
    """
    probe = (system.get("extra") or {}).get("probe") or {}
    texts = [facts["ip"]["value"]
             for result in probe.values()
             for facts in [(result or {}).get("facts") or {}]
             if "ip" in facts]

    subnets: set[str] = set()
    for text in texts:
        for ip in _IP_RE.findall(text):
            if _looks_like_mask(ip) or ip.startswith(("0.", "127.")) or ip == "255.255.255.255":
                continue
            subnets.add(_subnet_of(ip))
    if not subnets and system.get("ip"):
        subnets.add(_subnet_of(system["ip"]))
    return subnets


# Subnets with fewer active IPs than this are left off the plan entirely -- a household with a
# /24 per VLAN otherwise ends up with several rows showing little more than "1 Gerät", which is
# clutter, not information. The devices themselves are still fully visible elsewhere (the device
# list, the physical plan) -- this only trims what the Layer-3 overview draws.
_MIN_SUBNET_DEVICES = 3


_STALE_DAYS = 30


def _counts_in_layer3(system: dict) -> bool:
    """Whether a device counts towards a Layer-3 subnet: no Docker containers (same IP as their
    host) and no discovered device that has been offline for more than `_STALE_DAYS` days. An
    unparsable or missing `lastSeen` counts, so a data gap never hides a device."""
    if "docker" in (system.get("discoverySource") or "").split("+"):
        return False
    if system.get("discovered") and system.get("status") == "offline":
        try:
            seen = datetime.strptime(system.get("lastSeen") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - seen <= timedelta(days=_STALE_DAYS)
    return True


def _infer_router_hierarchy(routers: list[dict], raw_subnets: dict[str, set[str]]) -> dict[str, str | None]:
    """Which router is the effective *parent* of which (its upstream, closer to Internet), so a
    secondary router plugged into the household's primary one (a UCG behind a FritzBox) is
    drawn as a chain -- Internet -> FritzBox -> UCG -> its own networks -- instead of as two
    unrelated boxes both hanging directly off Internet.

    Nothing in this codebase ever sets a router's own `parentId` automatically (no controller
    reports an uplink for a gateway), so without this every router would render as its own root --
    in the Layer-3 plan and, via `_router_parents`, in the physical plan. Inferred instead from
    subnet containment, which needs no extra
    configuration: a downstream router's own interface set always includes its upstream's subnet
    too (its WAN/uplink side is an ordinary client address on the upstream router's LAN) plus
    subnets of its own the upstream router never sees -- so its raw subnet set is always a strict
    superset of its immediate upstream's. For each router, the smallest other router whose raw set
    is a strict subset of its own is picked as the immediate parent (the closest upstream hop, not
    a more distant ancestor further up the same chain). A human-set `parentId` that already points
    at another router in this list wins over the inference, same "confirmed data wins" rule as
    everywhere else in this app.

    A router with no probe data at all falls back (see `_router_subnets`) to the single subnet
    implied by its own stored `ip` -- still enough for this containment check to work as long as at
    least the *upstream* router's address is known, which discovery always has.
    """
    router_ids = {r["id"] for r in routers}
    parent_by_id: dict[str, str | None] = {}
    for r in routers:
        manual_parent = r.get("parentId")
        if manual_parent in router_ids:
            parent_by_id[r["id"]] = manual_parent
            continue
        own = raw_subnets.get(r["id"]) or set()
        # An empty set is a strict subset of everything; a router without any known subnet (no IP,
        # no controller networks) says nothing about the chain, so it is never picked as upstream.
        candidates = [o for o in routers
                      if o["id"] != r["id"] and raw_subnets.get(o["id"]) and raw_subnets[o["id"]] < own]
        parent_by_id[r["id"]] = min(candidates, key=lambda o: len(raw_subnets[o["id"]]))["id"] if candidates else None
    return parent_by_id


_ControllerNetwork = tuple[ipaddress.IPv4Network, "str | None", "str | None"]


def _controller_networks() -> list[_ControllerNetwork]:
    """Active controller networks (UniFi) as (IPv4 network, owner system id, VLAN id)."""
    networks: list[_ControllerNetwork] = []
    for resource in db.list_network_resources(kind="network", active_only=True):
        try:
            network = ipaddress.ip_network((resource.get("facts") or {}).get("cidr", ""), strict=False)
        except ValueError:
            continue
        if isinstance(network, ipaddress.IPv4Network):
            networks.append((network, resource.get("ownerSystemId"),
                             str((resource.get("facts") or {}).get("vlanId") or "") or None))
    return networks


def _subnet_for(ip: str, controller_networks: list[_ControllerNetwork]) -> str:
    """The narrowest controller network containing `ip`, else its /24 approximation."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return _subnet_of(ip)
    matches = [network for network, _, _ in controller_networks if address in network]
    return str(max(matches, key=lambda network: network.prefixlen)) if matches else _subnet_of(ip)


def _wan_uplink_subnets(controller_networks: list[_ControllerNetwork]) -> dict[str, set[str]]:
    """owner system id -> the subnet its active WAN interface address lies in.

    A UniFi gateway in a router cascade (FritzBox -> UCG) gets a private WAN address from the
    upstream router's LAN; the classic UniFi API reports it as `interfaceIp` on the WAN resource
    (unifi_classic_probe.py, db.set_wan_status). That subnet is what makes the gateway's own subnet
    set a strict superset of its upstream's, which `_infer_router_hierarchy` needs to chain it --
    the controller networks alone never include the upstream LAN. A public WAN address belongs to
    no LAN here and is ignored.
    """
    result: dict[str, set[str]] = {}
    for resource in db.list_network_resources(kind="wan", active_only=True):
        owner_id = resource.get("ownerSystemId")
        ip = str((resource.get("facts") or {}).get("interfaceIp") or "").strip()
        if not owner_id or not ip:
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address) or address.is_global:
            continue
        result.setdefault(owner_id, set()).add(_subnet_for(ip, controller_networks))
    return result


def _router_subnet_sets(routers: list[dict], controller_networks: list[_ControllerNetwork]) -> dict[str, set[str]]:
    """router id -> every subnet it has an address in: interface facts or its own IP (`_router_subnets`),
    its further known addresses (`systemAliases`, the "Weitere Adressen" a multi-homed gateway is
    seen under -- for a UniFi gateway in a cascade that includes its WAN address in the upstream
    LAN), the controller networks it owns, and the subnet of its WAN interface address.

    A /24 approximation (from probe facts or the router's IP) that overlaps an exact controller CIDR
    is dropped in favour of the CIDR, so one physical network never enters the chain inference twice.
    """
    active_cidrs = [network for network, _, _ in controller_networks]
    cidr_strs = {str(n) for n in active_cidrs}

    def approximation_kept(subnet: str) -> bool:
        if subnet in cidr_strs:
            return True
        try:
            net = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            return True
        return not any(isinstance(net, ipaddress.IPv4Network) and net.overlaps(c) for c in active_cidrs)

    owned: dict[str, set[str]] = {}
    for network, owner_id, _ in controller_networks:
        if owner_id:
            owned.setdefault(owner_id, set()).add(str(network))
    wan = _wan_uplink_subnets(controller_networks)

    def alias_subnets(router_id: str) -> set[str]:
        result: set[str] = set()
        for alias in db.list_aliases(router_id):
            ip = str(alias.get("ip") or "").strip()
            try:
                address = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if isinstance(address, ipaddress.IPv4Address) and address.is_private and not address.is_loopback:
                result.add(_subnet_for(ip, controller_networks))
        return result

    return {
        r["id"]: {s for s in _router_subnets(r) if approximation_kept(s)}
        | alias_subnets(r["id"]) | owned.get(r["id"], set()) | wan.get(r["id"], set())
        for r in routers
    }


def _router_parents(routers: list[dict]) -> dict[str, str | None]:
    """Upstream router per router for the physical plan -- the same inference the Layer-3 plan uses,
    so a cascade (FritzBox -> UCG) is drawn as a chain in both views rather than side by side."""
    return _infer_router_hierarchy(routers, _router_subnet_sets(routers, _controller_networks()))


def render_layer3(settings: dict | None = None) -> str:
    """Alternative view of the same inventory, grouped by IP subnet (/24) instead of by how
    devices are physically wired -- useful once a household has more than one subnet or VLAN (a
    guest network, an IoT VLAN on the same switches) where the physical `render()` above still
    only shows one wire.

    End-device subnet membership uses a controller-provided CIDR whenever one contains its stored
    IP, otherwise it falls back to the historic /24 approximation. Routers are placed more accurately: a router
    probed over SSH (Linux) is checked against *every* subnet its own interface table shows an address in
    (see `_router_subnets`), not just the one its single stored `ip` field happens to fall into --
    and routers are chained by inferred upstream/downstream relationship (`_infer_router_hierarchy`)
    rather than all lumped together as roots, so a household with FritzBox -> UCG -> its own
    LANs actually renders as that chain instead of two disconnected boxes.

    Routers are recognised by `kind == "router"` plus a stored IP or ownership of an active
    controller network, not by the IP's last octet; a router with neither has no derivable subnet
    and stays off this view (the physical plan is unaffected). A gateway's WAN interface address
    (`_wan_uplink_subnets`) adds the upstream LAN to its subnet set, which is what chains a UniFi
    gateway below the FritzBox in a router cascade. Device counts leave out Docker containers (they share their host's IP) and
    discovered devices that have been offline for more than `_STALE_DAYS` days.

    Subnet sets per router come from `_router_subnet_sets` (shared with the physical plan).

    A subnet a router shares with its own upstream is that upstream's LAN, not something the
    downstream router "serves" -- excluded from the downstream router's own networks (see
    `own_subnets` below) so it is attributed once, to whichever router actually owns it, and drawn
    as that router's own child row rather than claimed twice or attached to the wrong one.
    """
    settings = settings or db.get_settings()
    all_systems = db.list_systems()
    controller_networks = _controller_networks()
    network_owners = {owner_id for _, owner_id, _ in controller_networks if owner_id}
    routers = sorted(
        (s for s in all_systems if s["kind"] == "router" and (s.get("ip") or s["id"] in network_owners)),
        key=lambda r: r["name"].lower(),
    )
    others = [s for s in all_systems if s["kind"] != "router" and s.get("ip") and _counts_in_layer3(s)]

    controller_vlans_by_owner: dict[str, dict[str, str]] = {}
    for network, owner_id, vlan_id in controller_networks:
        if owner_id and vlan_id:
            controller_vlans_by_owner.setdefault(owner_id, {})[str(network)] = vlan_id

    raw_subnets = _router_subnet_sets(routers, controller_networks)
    router_vlans = controller_vlans_by_owner
    parent_by_id = _infer_router_hierarchy(routers, raw_subnets)

    own_subnets = {
        r["id"]: raw_subnets[r["id"]] - raw_subnets.get(parent_by_id.get(r["id"]), set())
        for r in routers
    }

    others_by_subnet: dict[str, list[dict]] = {}
    for s in others:
        others_by_subnet.setdefault(_subnet_for(s["ip"], controller_networks), []).append(s)

    # First router (in the already name-sorted list) to claim a subnet as its own wins -- a tie is
    # only possible between two routers whose subnet sets are identical, which is not something
    # `_infer_router_hierarchy` can tell apart anyway.
    subnet_owner: dict[str, str] = {}
    for r in routers:
        for subnet in own_subnets[r["id"]]:
            subnet_owner.setdefault(subnet, r["id"])

    subnet_nodes: dict[str, dict] = {}
    for subnet in sorted(set(others_by_subnet) | set(subnet_owner), key=_subnet_sort_key):
        owner_id = subnet_owner.get(subnet)
        members = others_by_subnet.get(subnet, [])
        # The owning router itself holds an active address in this subnet too -- counted here even
        # though it is drawn as its own box elsewhere in the chain, not repeated in this one.
        total = len(members) + (1 if owner_id else 0)
        if total < _MIN_SUBNET_DEVICES:
            continue
        vlan_id = router_vlans.get(owner_id, {}).get(subnet) if owner_id else None
        subtitle_parts = [f"{total} Gerät{'e' if total != 1 else ''}"]
        if vlan_id:
            subtitle_parts.append(f"VLAN {vlan_id}")
        if members:
            online = sum(1 for m in members if m["status"] == "online")
            subtitle_parts.append(f"{online} erreichbar" if online else "keins erreichbar")
        subnet_nodes[subnet] = {
            "id": f"subnet:{subnet}", "parentId": owner_id, "title": subnet,
            "subtitle": " · ".join(subtitle_parts), "fill": _COLORS["boxAlt"],
            # No device page behind a subnet; the id only wires up the edges.
            "link": False,
        }

    # Routers and kept subnets share one chain: a subnet node's `parentId` is the router that owns
    # it, a router's is its inferred (or human-set) upstream -- `_chain_layers`/`_edges_by_parent`
    # (the same generic layering the physical plan's Router/Verteilung sections use) don't care
    # which is which, so a mixed row of "further router" and "own network" siblings falls out of
    # the exact same code path with no special-casing needed here.
    chain_items = [
        {"id": r["id"], "parentId": parent_by_id.get(r["id"]), "title": r["name"],
         "subtitle": r["ip"], "status": r["status"]}
        for r in routers
    ] + list(subnet_nodes.values())

    layers = _chain_layers(chain_items)
    width = _canvas_width(max([len(layer) for layer in layers] + [1]))

    svg: list[str] = []
    y = 40
    svg.append(_label(40, y - 12, "Internet"))
    internet_svg, internet_anchor = _row([{
        "title": "Internet",
        "subtitle": settings.get("homeName") and f"Zugang für {settings['homeName']}" or "",
        "fill": _COLORS["boxAlt"],
    }], y, box_w_max=220, width=width)
    svg.append(internet_svg)
    previous = internet_anchor[0]
    y += _LAYER_GAP

    anchor_by_id: dict[str, tuple[float, float]] = {}
    for depth, layer in enumerate(layers):
        row_svg, anchors = _row(layer, y, box_w_max=220, width=width)
        svg.append(_edges(previous, anchors) if depth == 0
                  else _edges_by_parent(anchor_by_id, layer, anchors, previous))
        svg.append(row_svg)
        anchor_by_id.update(zip((i["id"] for i in layer), anchors))
        y += _LAYER_GAP

    if not chain_items:
        message = ("Noch keine Geräte mit bekannter Adresse erfasst." if not others_by_subnet else
                   f"Nur Netze mit weniger als {_MIN_SUBNET_DEVICES} Geräten gefunden — zur "
                   "Übersichtlichkeit ausgeblendet.")
        svg.append(
            f'<text x="{width / 2:.0f}" y="{y:.0f}" text-anchor="middle" fill="{_COLORS["muted"]}" '
            f'font-size="14">{_esc(message)}</text>'
        )
        y += 40

    height = y + 20
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" '
        f'width="100%" role="img" aria-label="Netzplan nach Subnetzen (Layer 3)" '
        f'font-family="Segoe UI, system-ui, sans-serif">'
        f'<rect width="{width}" height="{height:.0f}" fill="{_COLORS["bg"]}"/>'
        f'{"".join(svg)}{_legend(height)}</svg>'
    )
