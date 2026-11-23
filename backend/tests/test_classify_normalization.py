"""Hardening of the LLM classification: validity, protection of rule results, per-IP merging."""
import asyncio
import json

import pytest

from app import classify, prompts

SETTINGS = {"llmProvider": "ollama"}


def _setup(monkeypatch, entries, payloads=None):
    async def fake_chat(provider, settings, system, messages, purpose=None):
        if payloads is not None:
            payloads.append(json.loads(messages[0]["content"].split(":\n\n", 1)[1]))
        return type("R", (), {"text": json.dumps(entries)})()

    async def fake_validate(url):
        return True

    monkeypatch.setattr(classify.llm_providers, "chat", fake_chat)
    monkeypatch.setattr(classify.llm_providers, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(classify.vendor_docs, "validate", fake_validate)


def _finding(ip="192.168.1.1", **kw):
    base = {"ip": ip, "name": "Gerät", "kind": "other", "vendor": "ACME", "openPorts": [80],
            "services": [], "extra": {}}
    return base | kw


def _run(findings, **kw):
    return asyncio.run(classify.classify(findings, SETTINGS, **kw))


@pytest.mark.parametrize("raw", ["LOW", " low ", "niedrig", "unbekannt", 0])
def test_confidence_variants_discarded(monkeypatch, raw):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "kind": "nas", "confidence": raw}])
    by_ip, _ = _run([_finding()])
    assert by_ip == {}


@pytest.mark.parametrize("raw,expected", [("HIGH", "high"), (" Medium ", "medium"),
                                           (None, "medium"), ("", "medium")])
def test_confidence_variants_accepted(monkeypatch, raw, expected):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "kind": "nas", "confidence": raw}])
    by_ip, _ = _run([_finding()])
    assert by_ip["192.168.1.1"]["confidence"] == expected


def test_confidence_missing_is_medium(monkeypatch):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "kind": "nas"}])
    by_ip, _ = _run([_finding()])
    assert by_ip["192.168.1.1"]["confidence"] == "medium"


def test_apply_writes_normalized_confidence(monkeypatch):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "kind": "nas", "confidence": "HIGH"}])
    by_ip, _ = _run([_finding()])
    merged = classify.apply(_finding(), by_ip["192.168.1.1"])
    assert merged["extra"]["aiConfidence"] == "high"


def test_invalid_kind_keeps_rule_kind(monkeypatch):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "kind": "gadget", "confidence": "high"}])
    by_ip, _ = _run([_finding(kind="router", extra={"guessConfident": False})])
    assert by_ip["192.168.1.1"]["kind"] == ""
    assert classify.apply(_finding(kind="router"), by_ip["192.168.1.1"])["kind"] == "router"


def test_invalid_importance_keeps_rule_importance(monkeypatch):
    _setup(monkeypatch, [{"ip": "192.168.1.1", "importance": "wichtig", "confidence": "high"}])
    by_ip, _ = _run([_finding()])
    assert by_ip["192.168.1.1"]["importance"] == ""
    assert classify.apply(_finding(importance="critical"), by_ip["192.168.1.1"])["importance"] == "critical"
    assert classify.apply(_finding(importance="low"), by_ip["192.168.1.1"])["importance"] == "low"


@pytest.mark.parametrize("ai", ["low", "normal"])
def test_gateway_critical_not_downgraded(ai):
    out = classify.apply(_finding(kind="router", importance="critical"),
                         {"importance": ai, "confidence": "high"})
    assert out["importance"] == "critical"


def test_ai_critical_upgrades_normal():
    out = classify.apply(_finding(importance="normal"), {"importance": "critical"})
    assert out["importance"] == "critical"


def test_confident_rule_kind_kept():
    cls = {"kind": "nas", "confidence": "high"}
    assert classify.apply(_finding(kind="router"), cls)["kind"] == "router"
    assert classify.apply(_finding(kind="router", extra={"guessConfident": True}), cls)["kind"] == "router"
    assert classify.apply(_finding(kind="other"), cls)["kind"] == "nas"
    assert classify.apply(_finding(kind="router", extra={"guessConfident": False}), cls)["kind"] == "nas"


def test_apply_to_system_protects_critical_and_kind():
    system = {"ip": "192.168.1.1", "kind": "router", "importance": "critical", "name": "Box",
              "extra": {}, "confirmed": False}
    patch = classify.apply_to_system(system, {"kind": "nas", "importance": "low", "purpose": "Zweck",
                                              "confidence": "high"})
    assert "kind" not in patch and "importance" not in patch
    assert patch["purpose"] == "Zweck"
    confirmed = classify.apply_to_system(system | {"confirmed": True},
                                         {"kind": "nas", "importance": "low", "purpose": "Zweck"})
    assert set(confirmed) - {"discoverySource", "extra"} == {"purpose"}


def test_missing_doc_url_alone_not_candidate():
    f = _finding(kind="router", purpose="Router", extra={"guessConfident": True})
    assert classify.needs_classification(f) is False
    assert classify.needs_classification(f | {"docUrl": "https://x.example"}) is False
    nop = f | {"purpose": ""}
    assert classify.needs_classification(nop) is True
    assert classify.needs_classification(nop | {"docUrl": "https://x.example"}) is True


def _two_for_ip():
    net = _finding(ip="10.0.0.5", hostname="h", vendor="",
                   services=[{"port": 22, "service": "ssh"}, {"port": 80, "service": "http"}],
                   extra={"mdns": [{"type": "_a", "name": "a"}], "ssdp": [{"description": "d1"}]})
    pve = _finding(ip="10.0.0.5", hostname="", vendor="Proxmox", kind="vm", name="pve-vm",
                   discoverySource="proxmox", extra={"proxmox": {},
                                                     "mdns": [{"type": "_a", "name": "a"}, {"type": "_b", "name": "b"}],
                                                     "ssdp": [{"description": "d2"}]},
                   services=[{"port": 80, "service": "http"}, {"port": 443, "service": "https"}])
    return net, pve


def test_same_ip_findings_merged_into_one_evidence(monkeypatch):
    payloads = []
    _setup(monkeypatch, [{"ip": "10.0.0.5", "kind": "server", "confidence": "high"}], payloads)
    _run(list(_two_for_ip()))
    assert len(payloads) == 1 and len(payloads[0]) == 1
    ev = payloads[0][0]
    assert ev["ip"] == "10.0.0.5" and ev["hostname"] == "h" and ev["macVendor"] == "Proxmox"
    assert ev["openPorts"] == ["22 (ssh)", "80 (http)", "443 (https)"]
    assert [m["type"] for m in ev["mdnsServices"]] == ["_a", "_b"]
    assert ev["upnp"] == ["d1", "d2"]


def test_batch_counts_ips(monkeypatch):
    payloads = []
    _setup(monkeypatch, [], payloads)
    _run([_finding(ip=f"10.0.0.{i % 6}") for i in range(12)])
    assert len(payloads) == 1
    payloads.clear()
    _run([_finding(ip=f"10.0.1.{i}") for i in range(11)])
    assert len(payloads) == 2


def test_merge_excludes_containers_and_empty_ip(monkeypatch):
    payloads = []
    _setup(monkeypatch, [], payloads)
    container = {"name": "c", "kind": "container", "ip": "10.0.0.5", "openPorts": [81],
                 "services": [{"port": 81, "service": "x"}], "extra": {"docker": {}}}
    noip = _finding(ip="")
    net, _ = _two_for_ip()
    _run([net, container, noip])
    assert len(payloads) == 1
    assert [e["ip"] for e in payloads[0]] == ["10.0.0.5"]
    assert "81 (x)" not in payloads[0][0]["openPorts"]


def test_result_applied_to_all_findings_of_ip():
    net, pve = _two_for_ip()
    cls = {"kind": "server", "name": "KI-Name", "confidence": "high"}
    out_pve = classify.apply(pve, cls)
    assert out_pve["name"] == "pve-vm" and out_pve["kind"] == "vm"
    out_net = classify.apply(net | {"kind": "other"}, cls)
    assert out_net["kind"] == "server" and out_net["name"] == "KI-Name"


def test_prompt_has_no_order_requirement():
    assert "Reihenfolge" not in prompts.CLASSIFY_SYSTEM


def test_answer_in_different_order_mapped_by_ip(monkeypatch):
    _setup(monkeypatch, [{"ip": "10.0.0.2", "kind": "nas", "confidence": "high"},
                         {"ip": "10.0.0.1", "kind": "printer", "confidence": "high"}])
    by_ip, _ = _run([_finding(ip="10.0.0.1"), _finding(ip="10.0.0.2")])
    assert by_ip["10.0.0.1"]["kind"] == "printer" and by_ip["10.0.0.2"]["kind"] == "nas"
