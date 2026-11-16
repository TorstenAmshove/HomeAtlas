def _mk(db, name, **kw):
    return db.create_system({"name": name, "discoveryKey": f"k:{name}", "discovered": 1, **kw})


def _pairs(db):
    return {(c["aName"], c["bName"]): c["reasons"] for c in db.find_duplicate_candidates()}


def test_same_hostname_flagged(temp_db):
    _mk(temp_db, "a", hostname="Router.fritz.box")
    _mk(temp_db, "b", hostname="router")
    _mk(temp_db, "c", hostname="")
    _mk(temp_db, "d", hostname="")
    _mk(temp_db, "e", hostname="10.0.0.1")
    _mk(temp_db, "f", hostname="10.0.0.1")
    assert list(_pairs(temp_db).values()) == [["hostname"]]


def test_same_vendor_only_not_flagged(temp_db):
    _mk(temp_db, "a", vendor="AVM")
    _mk(temp_db, "b", vendor="AVM")
    assert temp_db.find_duplicate_candidates() == []


def test_identical_vendor_and_model_not_flagged(temp_db):
    # Two identical devices are normal in a home, not a duplicate.
    _mk(temp_db, "a", vendor="AVM", model="7590")
    _mk(temp_db, "b", vendor="avm", model="7590")
    assert temp_db.find_duplicate_candidates() == []


def test_self_reported_name_flagged(temp_db):
    _mk(temp_db, "a", extra={"ssdp": [{"description": {"friendlyName": "Box"}}]})
    _mk(temp_db, "b", extra={"mdns": [{"name": "box"}]})
    _mk(temp_db, "c", extra={"ssdp": "kaputt", "mdns": None})
    _mk(temp_db, "d")
    assert list(_pairs(temp_db).values()) == [["selfName"]]


def test_pair_with_several_reasons_is_one_entry(temp_db):
    _mk(temp_db, "a", hostname="gw", extra={"mdns": [{"name": "Gateway"}]})
    _mk(temp_db, "b", hostname="gw", extra={"mdns": [{"name": "gateway"}]})
    result = temp_db.find_duplicate_candidates()
    assert len(result) == 1 and set(result[0]["reasons"]) == {"hostname", "selfName"}


def test_three_devices_same_hostname_give_three_pairs(temp_db):
    for n in "abc":
        _mk(temp_db, n, hostname="gw")
    assert len(temp_db.find_duplicate_candidates()) == 3


def test_generic_name_shared_by_many_not_flagged(temp_db):
    for n in "abcd":
        _mk(temp_db, n, hostname="espressif", extra={"mdns": [{"name": "Smart Plug"}]})
    assert temp_db.find_duplicate_candidates() == []


def test_dismissed_pair_not_suggested_after_rescan(temp_db):
    a = _mk(temp_db, "a", hostname="gw")
    b = _mk(temp_db, "b", hostname="gw")
    temp_db.dismiss_duplicate(b["id"], a["id"])
    temp_db.dismiss_duplicate(a["id"], b["id"])  # idempotent
    temp_db.upsert_discovered_system({"discoveryKey": "k:a", "ip": "10.0.0.5", "hostname": "gw"})
    assert temp_db.find_duplicate_candidates() == []


def test_merged_pair_no_longer_suggested(temp_db):
    a = _mk(temp_db, "a", hostname="gw")
    b = _mk(temp_db, "b", hostname="gw")
    temp_db.merge_systems(a["id"], b["id"])
    assert temp_db.find_duplicate_candidates() == []
