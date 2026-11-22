import asyncio

from app import db, docs


def _gen():
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))


def _side(zone):
    return {"zoneId": zone, "target": "ANY", "ips": [], "ipGroupId": "", "portType": "ANY", "port": "", "portGroupId": ""}


def _policy(pid, name, index, action, src, dst, **kw):
    d = {"id": pid, "name": name, "index": index, "enabled": True, "predefined": False, "action": action,
         "protocol": "tcp", "ipVersion": "BOTH", "connectionState": "ALL", "source": _side(src),
         "destination": {**_side(dst), "portType": "SPECIFIC", "port": "443"}, "unsupported": []}
    d.update(kw)
    return {"kind": "policy", "key": f"policy:{pid}", "data": d}


def _facts(name="Allow |`<b>"):
    zone = lambda i, n: {"kind": "zone", "key": f"zone:{i}", "data": {"id": i, "name": n, "zoneKey": "", "networkIds": []}}  # noqa: E731
    return [zone("g", "Gäste"), zone("s", "Server"),
            _policy("d", "Block All Traffic", 2147483647, "BLOCK", "g", "s", protocol="all", destination=_side("s")),
            _policy("a", name, 10, "ALLOW", "g", "s"),
            _policy("x", "alt", 20, "ALLOW", "s", "g", enabled=False)]


def test_empty_state(temp_db):
    _gen()
    assert "Noch keine Firewall-Daten" in db.get_doc_page("wer-darf-mit-wem")["bodyMd"]


def test_matrix_exceptions_hints_and_escaping(temp_db):
    db.replace_firewall_facts("unifi", "acc", _facts())
    _gen()
    body = db.get_doc_page("wer-darf-mit-wem")["bodyMd"]
    assert "Zonenmatrix" in body and "teilweise (1)" in body
    assert "Gäste → Server: gesperrt, außer" in body
    assert "deaktivierte Regel" in body and "alt" in body
    assert "|`" not in body and "<b>" not in body


def test_unsupported_rule_makes_cell_unclear(temp_db):
    facts = _facts()
    facts[3]["data"]["unsupported"] = ["schedule"]
    db.replace_firewall_facts("unifi", "acc", facts)
    _gen()
    assert "unklar" in db.get_doc_page("wer-darf-mit-wem")["bodyMd"]


def test_order_decides_matrix_text(temp_db):
    facts = [f for f in _facts() if f["key"] != "policy:d"]
    facts += [_policy("b", "Block All", 40000, "BLOCK", "g", "s", protocol="all",
                      destination=_side("s")),
              _policy("d2", "Allow All Traffic", 2147483647, "ALLOW", "g", "s", protocol="all",
                      destination=_side("s"))]
    db.replace_firewall_facts("unifi", "acc", facts)
    _gen()
    body = db.get_doc_page("wer-darf-mit-wem")["bodyMd"]
    assert "Gäste → Server: gesperrt, außer" in body and "aber gesperrt" not in body
