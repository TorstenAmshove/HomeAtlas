import asyncio

from app import classify, db, pipeline


def _f(ip, **kw):
    return {"discoveryKey": f"ip:{ip}", "ip": ip, "name": ip, "kind": "other", "openPorts": [80],
            "extra": {}, **kw}


def _run(findings, monkeypatch, answers):
    calls = []

    async def fake(fs, settings, log=None, force=False):
        calls.append([f["ip"] for f in fs])
        return {f["ip"]: answers[f["ip"]] for f in fs if f["ip"] in answers}, []

    monkeypatch.setattr(classify, "classify", fake)
    out, warnings = asyncio.run(pipeline._classify_new_findings(findings, {}, lambda m: None))
    return out, calls


GOOD = {"kind": "router", "name": "KI", "purpose": "Zweck", "confidence": "high"}


def test_second_scan_sends_nothing(temp_db, monkeypatch):
    db.upsert_discovered_system(_f("192.168.1.5"))
    out, calls = _run([_f("192.168.1.5")], monkeypatch, {})
    assert calls == [] and out[0]["kind"] == "other"


def test_new_findings_per_source(temp_db, monkeypatch):
    fs = [_f("192.168.1.6", discoverySource="unifi", extra={"unifi": {}}),
          _f("192.168.1.7", discoverySource="proxmox", extra={"proxmox": {}}),
          _f("192.168.1.8", discoverySource="omada", extra={"omada": {}}),
          _f("192.168.1.9", discoverySource="adguard")]
    out, calls = _run(fs, monkeypatch, {f["ip"]: GOOD for f in fs})
    assert calls == [[f["ip"] for f in fs]]
    assert all(o["purpose"] == "Zweck" for o in out)


def test_discarded_answer_not_retried_and_known_other_skipped(temp_db, monkeypatch):
    f = _f("192.168.1.10")
    _, calls = _run([f], monkeypatch, {})  # low confidence -> no answer
    assert calls == [["192.168.1.10"]]
    db.upsert_discovered_system(f)
    _, calls = _run([_f("192.168.1.10")], monkeypatch, {})
    assert calls == []


def test_only_new_findings_get_applied(temp_db, monkeypatch):
    db.upsert_discovered_system(_f("192.168.1.11"))
    out, calls = _run([_f("192.168.1.11"), _f("192.168.1.12")], monkeypatch,
                      {"192.168.1.11": GOOD, "192.168.1.12": GOOD})
    assert calls == [["192.168.1.12"]]
    assert out[0]["kind"] == "other" and out[1]["kind"] == "router"


def test_same_hardware_two_findings_no_crash(temp_db, monkeypatch):
    fs = [_f("192.168.1.13"), _f("192.168.1.13", discoverySource="unifi", extra={"unifi": {}})]
    out, _ = _run(fs, monkeypatch, {"192.168.1.13": GOOD})
    assert out[0]["kind"] == "router" and out[1]["kind"] == "other"


def test_ai_result_survives_next_scan(temp_db, monkeypatch):
    out, _ = _run([_f("192.168.1.14")], monkeypatch, {"192.168.1.14": GOOD})
    db.upsert_discovered_system(out[0])
    again, calls = _run([_f("192.168.1.14")], monkeypatch, {})
    row, _ = db.upsert_discovered_system(again[0])
    assert calls == [] and row["kind"] == "router" and row["purpose"] == "Zweck"
