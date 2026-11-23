from app import docs


def _r(name, ip="10.0.0.1", importance="normal", extra=None):
    return {"kind": "router", "name": name, "ip": ip, "importance": importance, "extra": extra}


def test_critical_wins_over_gateway():
    a, b, c = _r("A", extra={"isGateway": True}), _r("B", importance="critical"), _r("C")
    primary, others = docs._pick_router([a, b, c])
    assert primary is b and others == [a, c]


def test_gateway_wins_without_critical():
    a, b = _r("A", extra=None), _r("B", extra={"isGateway": True})
    assert docs._pick_router([a, b])[0] is b


def test_first_otherwise_and_ties():
    a, b = _r("A"), _r("B")
    assert docs._pick_router([a, b]) == (a, [b])
    c, d = _r("C", importance="critical"), _r("D", importance="critical")
    assert docs._pick_router([a, c, d])[0] is c


def test_ignores_non_routers_and_empty():
    assert docs._pick_router([{"kind": "nas", "extra": None}]) == (None, [])


def test_section_hint():
    a, b = _r("A"), _r("B|x", ip="10.0.0.2")
    one = docs._emergency_section({"router": a, "other_routers": []})
    assert "Weitere Router" not in one
    many = docs._emergency_section({"router": a, "other_routers": [b]})
    assert "Weitere Router: **B\\|x** (10.0.0.2)" in many
    assert "noch kein Router" in docs._emergency_section({"router": None})
