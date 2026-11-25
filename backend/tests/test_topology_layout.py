"""Topology plan (#143): status word, legend, overflow/duplicates, stable subnet order, min width."""
import re
import subprocess
import sys

from app import topology


def _mk(db, kind, name, ip, n, **extra):
    return db.create_system({"kind": kind, "name": name, "ip": ip,
                             "discoveryKey": f"k:{n}", **extra})


def _widths(svg):
    return [float(w) for w in re.findall(r'<rect x="[\d.-]+" y="[\d.]+" width="([\d.]+)" height="64"', svg)]


def _viewbox_w(svg):
    return int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1))


def _subnet_plan(db, subnets, reverse=False):
    n = 0
    for base in (reversed(subnets) if reverse else subnets):
        for host in range(10, 13):
            n += 1
            _mk(db, "pc", f"pc{n}", f"{base}.{host}", n)


def test_subnet_sort_key_orders_prefix_after_address():
    keys = sorted(["192.168.10.0/24", "10.0.0.0/26", "unbekanntes Netz", "10.0.0.0/24", "192.168.2.0/24"],
                  key=topology._subnet_sort_key)
    assert keys == ["10.0.0.0/24", "10.0.0.0/26", "192.168.2.0/24", "192.168.10.0/24", "unbekanntes Netz"]


def test_layer3_subnets_sorted_numerically(temp_db):
    for reverse in (False, True):
        for s in temp_db.list_systems():
            temp_db.delete_system(s["id"])
        _subnet_plan(temp_db, ["192.168.10", "10.0.0", "192.168.2"], reverse)
        svg = topology.render_layer3({})
        order = [m for m in re.findall(r"(\d+\.\d+\.\d+\.0/24)", svg)]
        assert order == ["10.0.0.0/24", "192.168.2.0/24", "192.168.10.0/24"]


def test_layer3_order_independent_of_hash_seed():
    code = (
        "import sys, re; from app import topology as t\n"
        "subs = {'192.168.10.0/24','10.0.0.0/24','192.168.2.0/24','172.16.0.0/24'}\n"
        "print(sorted(subs, key=t._subnet_sort_key))"
    )
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={"PYTHONHASHSEED": seed, "PATH": ""}, check=True).stdout
            for seed in ("1", "2", "3")}
    assert len(outs) == 1


def test_layer3_subnet_boxes_have_no_system_id(temp_db):
    _mk(temp_db, "router", "Router", "10.0.0.1", 0)
    _subnet_plan(temp_db, ["10.0.0"])
    svg = topology.render_layer3({})
    assert "10.0.0.0/24" in svg
    assert 'data-system-id="subnet:' not in svg
    assert svg.count("data-system-id=") == 1


def test_box_shows_status_word(temp_db):
    _mk(temp_db, "router", "R-On", "10.0.0.1", 1, status="online")
    _mk(temp_db, "network", "SW-Off", "10.0.0.2", 2, status="offline")
    _mk(temp_db, "network", "SW-Unk", "10.0.0.3", 3, status="unknown")
    svg = topology.render({})
    assert "● erreichbar" in svg and "● nicht erreichbar" in svg and "● unbekannt" in svg
    assert "● unbekannt" in topology.render_layer3({}) or "● erreichbar" in topology.render_layer3({})


def test_layer3_has_legend_and_status(temp_db):
    _mk(temp_db, "router", "Router", "10.0.0.1", 0, status="offline")
    svg = topology.render_layer3({})
    assert "● nicht erreichbar" in svg
    assert 'r="5"' in svg  # legend dots


def test_internet_and_subnet_boxes_have_no_status_word(temp_db):
    _subnet_plan(temp_db, ["10.0.0"])
    assert "●" not in topology.render_layer3({})


def test_critical_router_drawn_once(temp_db):
    r = _mk(temp_db, "router", "Kritischer Router", "10.0.0.1", 1, importance="critical")
    sw = _mk(temp_db, "network", "Kritischer Switch", "10.0.0.2", 2, importance="critical")
    svg = topology.render({})
    assert svg.count(f'data-system-id="{r["id"]}"') == 1
    assert svg.count(f'data-system-id="{sw["id"]}"') == 1


def test_overflow_devices_not_drawn_are_not_in_svg(temp_db):
    for i in range(7):
        _mk(temp_db, "router", f"R{i}", f"10.0.{i}.1", i)
    for i in range(11):
        _mk(temp_db, "network", f"N{i}", f"10.1.{i}.2", 100 + i)
    svg = topology.render({})
    assert svg.count("data-system-id=") == 6 + 10


def test_boundary_counts_fully_drawn(temp_db):
    for i in range(6):
        _mk(temp_db, "router", f"R{i}", f"10.0.{i}.1", i)
    for i in range(10):
        _mk(temp_db, "network", f"N{i}", f"10.1.{i}.2", 100 + i)
    assert topology.render({}).count("data-system-id=") == 16


def test_critical_overflow_beyond_cap(temp_db):
    for i in range(12):
        _mk(temp_db, "server", f"S{i}", f"10.0.0.{10 + i}", i, importance="critical")
    assert topology.render({}).count("data-system-id=") == 10


def test_critical_router_beyond_router_cap_is_drawn_as_critical(temp_db):
    for i in range(6):
        _mk(temp_db, "router", f"A{i}", f"10.0.{i}.1", i)
    extra = _mk(temp_db, "router", "Z-Extra", "10.9.9.1", 50, importance="critical")
    svg = topology.render({})
    assert svg.count(f'data-system-id="{extra["id"]}"') == 1


def test_row_never_narrower_than_min_box_width(temp_db):
    for i in range(14):
        _subnet_plan_n = i * 3
        for host in range(10, 13):
            _mk(temp_db, "pc", f"pc{i}-{host}", f"10.{i}.0.{host}", _subnet_plan_n + host)
    svg = topology.render_layer3({})
    assert min(_widths(svg)) >= 90
    assert _viewbox_w(svg) > 1000


def test_physical_row_min_width_and_small_plan_keeps_width(temp_db):
    _mk(temp_db, "router", "R", "10.0.0.1", 1)
    assert _viewbox_w(topology.render({})) == 1000
    for i in range(10):
        _mk(temp_db, "server", f"S{i}", f"10.0.0.{10 + i}", 10 + i, importance="critical")
    svg = topology.render({})
    assert min(_widths(svg)) >= 90


def test_long_title_truncated_at_min_width(temp_db):
    _mk(temp_db, "router", "Ein-sehr-langer-Routername-der-nicht-passt", "10.0.0.1", 1)
    for i in range(14):
        for host in range(10, 13):
            _mk(temp_db, "pc", f"p{i}{host}", f"10.{i}.0.{host}", i * 20 + host)
    assert "…" in topology.render_layer3({})


def _fill(db, base, count, start=0, **extra):
    for i in range(count):
        _mk(db, "pc", f"{base}-{i}", f"{base}.{20 + i}", f"{base}{start + i}", **extra)


def test_layer3_router_without_gateway_ending(temp_db):
    r = _mk(temp_db, "router", "Router5", "192.168.1.5", "r")
    _fill(temp_db, "192.168.1", 3)
    assert f'data-system-id="{r["id"]}"' in topology.render_layer3({})


def test_layer3_router_without_ip_is_skipped(temp_db):
    r = temp_db.create_system({"kind": "router", "name": "NoIp", "discoveryKey": "k:r"})
    _fill(temp_db, "192.168.1", 3)
    assert f'data-system-id="{r["id"]}"' not in topology.render_layer3({})


def test_layer3_counts_exclude_docker_containers(temp_db):
    _fill(temp_db, "192.168.1", 2)
    _mk(temp_db, "container", "c1", "192.168.1.30", "c1", discoverySource="docker")
    _mk(temp_db, "container", "c2", "192.168.1.30", "c2", discoverySource="unifi+docker")
    assert "192.168.1.0/24" not in topology.render_layer3({})  # only 2 counted -> below threshold
    _mk(temp_db, "pc", "dockerish", "192.168.1.31", "dk", discoverySource="dockerhub")
    assert "3 Geräte" in topology.render_layer3({})


def _days_ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_layer3_counts_exclude_long_offline(temp_db):
    _fill(temp_db, "192.168.1", 2)
    old = _mk(temp_db, "pc", "old", "192.168.1.40", "old", discovered=1, status="offline")
    temp_db.update_system(old["id"], {"lastSeen": _days_ago(31)})
    assert "192.168.1.0/24" not in topology.render_layer3({})
    recent = _mk(temp_db, "pc", "recent", "192.168.1.41", "rec", discovered=1, status="offline")
    temp_db.update_system(recent["id"], {"lastSeen": _days_ago(29)})
    assert "3 Geräte" in topology.render_layer3({})


def test_layer3_exact_cidr_beats_24_approximation(temp_db, monkeypatch):
    r = _mk(temp_db, "router", "R", "192.168.1.1", "r")
    _fill(temp_db, "192.168.1", 3)
    monkeypatch.setattr(topology.db, "list_network_resources", lambda **kw: [
        {"ownerSystemId": r["id"], "facts": {"cidr": "192.168.1.0/26"}}])
    svg = topology.render_layer3({})
    assert "192.168.1.0/26" in svg and "192.168.1.0/24" not in svg


# --- edges only from parentId; router subnets from the Linux `ip` fact (#229) ------------------

def _probe(ip_text):
    return {"probe": {"ssh:x": {"ok": True, "facts": {"ip": {"label": "Netzwerkadressen", "value": ip_text}}}}}


def test_router_subnets_from_linux_ip_fact_and_fallback():
    multi = {"ip": "10.0.0.1", "extra": _probe("eth0 10.0.0.1/24\neth1 192.168.5.1/24\nlo 127.0.0.1/8")}
    assert topology._router_subnets(multi) == {"10.0.0.0/24", "192.168.5.0/24"}
    assert topology._router_subnets({"ip": "10.9.9.9", "extra": {}}) == {"10.9.9.0/24"}


def test_router_subnets_ignore_legacy_platform_facts():
    legacy = {"ip": "10.0.0.1", "extra": {"probe": {"ssh:x": {"ok": True, "facts": {
        "ip_addresses": {"label": "x", "value": "172.16.1.1/24"},
        "neighbors": {"label": "x", "value": "identity=sw"},
        "vlan": {"label": "x", "value": "vlan-id=10"},
    }}}}}
    assert topology._router_subnets(legacy) == {"10.0.0.0/24"}


def test_important_device_edge_from_parent_id_and_unknown_parent_falls_back(temp_db):
    router = _mk(temp_db, "router", "GW", "10.0.0.1", 1)
    switch = _mk(temp_db, "network", "SW", "10.0.0.2", 2, parentId=router["id"])
    known = _mk(temp_db, "server", "Srv", "10.0.0.3", 3, parentId=switch["id"], importance="critical")
    orphan = _mk(temp_db, "server", "Orphan", "10.0.0.4", 4, parentId="does-not-exist", importance="critical")
    svg = topology.render()
    assert known["name"] in svg and orphan["name"] in svg


# --- #257: continuous edges, grouping by parent, separate heights for overlapping groups ---------

_PATH_RE = re.compile(r'<path d="M (\d+) (\d+) ([VH]) (\d+)"')


def _paths(svg):
    return [(int(x), int(y), kind, int(to)) for x, y, kind, to in _PATH_RE.findall(svg)]


def _box_x(svg, name):
    """Centre x of the box titled `name` (its title text is centred)."""
    return int(re.search(rf'<text x="(\d+)" y="\d+" text-anchor="middle" fill="[^"]+" font-size="13" '
                         rf'font-weight="600">{name}</text>', svg).group(1))


def _connected(paths, parent_x, child_x):
    """A V-H-V route from the parent's x down to the child's x exists."""
    for x, y, kind, to in paths:
        if kind == "V" and x == parent_x:
            mid = to
            span = (min(parent_x, child_x), max(parent_x, child_x))
            has_h = parent_x == child_x or any(
                k == "H" and hy == mid and min(hx, hto) <= span[0] and max(hx, hto) >= span[1]
                for hx, hy, k, hto in paths)
            if has_h and any(k == "V" and vx == child_x and vy == mid for vx, vy, k, _ in paths):
                return True
    return False


def test_edges_single_offset_child_has_horizontal():
    for parent_x, child_x in ((284, 500), (700, 300)):
        paths = _paths(topology._edges((parent_x, 400), [(child_x, 490)]))
        mid = 400 + topology._BOX_H + (topology._LAYER_GAP - topology._BOX_H) / 2
        assert (parent_x, 464, "V", round(mid)) in paths
        assert (min(parent_x, child_x), round(mid), "H", max(parent_x, child_x)) in paths
        assert (child_x, round(mid), "V", 490) in paths


def test_edges_child_directly_below_has_no_horizontal():
    paths = _paths(topology._edges((500, 400), [(500, 490)]))
    assert [p for p in paths if p[2] == "H"] == []


def test_single_offset_child_edge_is_continuous(temp_db):
    router = _mk(temp_db, "router", "GW", "10.0.0.1", 1)
    sw_a = _mk(temp_db, "network", "SWA", "10.0.0.2", 2, parentId=router["id"])
    _mk(temp_db, "network", "SWB", "10.0.0.3", 3, parentId=router["id"])
    _mk(temp_db, "server", "Kind", "10.0.0.4", 4, parentId=sw_a["id"], importance="critical")
    svg = topology.render()
    parent_x, child_x = _box_x(svg, "SWA"), _box_x(svg, "Kind")
    assert parent_x != child_x
    assert _connected(_paths(svg), parent_x, child_x)


def test_layer3_single_child_edge_is_continuous(temp_db):
    paths = _paths(topology._edges((200, 100), [(500, 190)]))
    assert (200, 177, "H", 500) in paths  # render_layer3 uses the same `_edges`


def test_important_devices_grouped_in_parent_order(temp_db):
    router = _mk(temp_db, "router", "GW", "10.0.0.1", 1)
    sw_a = _mk(temp_db, "network", "SWA", "10.0.0.2", 2, parentId=router["id"])
    sw_b = _mk(temp_db, "network", "SWB", "10.0.0.3", 3, parentId=router["id"])
    _mk(temp_db, "server", "Bx1", "10.0.0.4", 4, parentId=sw_b["id"], importance="critical")
    _mk(temp_db, "server", "Ax1", "10.0.0.5", 5, parentId=sw_a["id"], importance="critical")
    _mk(temp_db, "server", "Ohne", "10.0.0.6", 6, importance="critical")
    _mk(temp_db, "server", "Bx2", "10.0.0.7", 7, parentId=sw_b["id"], importance="critical")
    svg = topology.render()
    order = sorted(["Bx1", "Ax1", "Ohne", "Bx2"], key=lambda n: _box_x(svg, n))
    assert order == ["Ax1", "Bx1", "Bx2", "Ohne"]
    paths = _paths(svg)
    for parent, child in (("SWA", "Ax1"), ("SWB", "Bx1"), ("SWB", "Bx2")):
        assert _connected(paths, _box_x(svg, parent), _box_x(svg, child))


def test_order_by_parent_is_stable_and_puts_parentless_last():
    anchors = {"a": (300, 0), "b": (700, 0)}
    items = [{"id": "1", "parentId": "b"}, {"id": "2", "parentId": None}, {"id": "3", "parentId": "a"},
             {"id": "4", "parentId": "b"}, {"id": "5", "parentId": "gone"}]
    assert [i["id"] for i in topology._order_by_parent(items, anchors)] == ["3", "1", "4", "2", "5"]


def _h_heights(svg):
    return [y for _x, y, kind, _to in _paths(svg) if kind == "H"]


def test_overlapping_parent_groups_use_different_heights():
    anchors = {"a": (300, 100), "b": (500, 100)}
    layer = [{"id": "1", "parentId": "a"}, {"id": "2", "parentId": "b"}]
    svg = topology._edges_by_parent(anchors, layer, [(600, 190), (400, 190)], (500, 0))
    heights = _h_heights(svg)
    assert len(heights) == 2 and heights[0] != heights[1]
    paths = _paths(svg)
    assert _connected(paths, 300, 600) and _connected(paths, 500, 400)
    # Stems start at the parent's bottom edge and every drop ends at the child's top: no gap.
    assert {(x, y) for x, y, k, _ in paths if k == "V" and x in (300, 500) and y == 164} == {(300, 164), (500, 164)}
    assert sorted(to for x, _y, k, to in paths if k == "V" and x in (400, 600)) == [190, 190]


def test_non_overlapping_parent_groups_keep_mid_y():
    anchors = {"a": (200, 100), "b": (700, 100)}
    layer = [{"id": "1", "parentId": "a"}, {"id": "2", "parentId": "b"}]
    svg = topology._edges_by_parent(anchors, layer, [(300, 190), (800, 190)], (500, 0))
    assert _h_heights(svg) == [177, 177]


def test_more_than_four_overlapping_groups_clamp():
    anchors = {str(i): (100 + 10 * i, 100) for i in range(5)}
    layer = [{"id": f"c{i}", "parentId": str(i)} for i in range(5)]
    svg = topology._edges_by_parent(anchors, layer, [(900, 190)] * 5, (500, 0))
    heights = _h_heights(svg)
    assert len(set(heights)) == topology._MAX_EDGE_LEVELS
    assert all(164 < h < 190 for h in heights)  # between parent bottom and child top


def test_layout_without_offset_children_unchanged(temp_db):
    # Internet -> router -> switch -> one critical child, all centred: the exact pre-#257 paths.
    router = _mk(temp_db, "router", "GW", "10.0.0.1", 1)
    switch = _mk(temp_db, "network", "SW", "10.0.0.2", 2, parentId=router["id"])
    _mk(temp_db, "server", "Srv", "10.0.0.3", 3, parentId=switch["id"], importance="critical")
    assert _paths(topology.render()) == [
        (500, 104, "V", 117), (500, 117, "V", 130), (500, 194, "V", 207), (500, 207, "V", 220),
        (500, 284, "V", 297), (500, 297, "V", 310)]
