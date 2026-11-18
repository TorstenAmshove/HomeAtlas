import asyncio

from app import classify


def _container(name, project):
    return {"name": name, "kind": "container", "ip": "192.168.1.20", "discoverySource": "docker",
            "openPorts": [80], "extra": {"docker": {"composeProject": project}}}


CLS = {"kind": "vm", "name": "Proxmox VM oder Container", "purpose": "Zweck", "confidence": "high"}


def test_containers_with_same_ip_untouched():
    host = {"name": "host", "kind": "other", "ip": "192.168.1.20", "openPorts": [22], "extra": {}}
    c1, c2 = _container("postgres · a", "a"), _container("postgres · b", "b")
    assert [classify.needs_classification(f) for f in (host, c1, c2)] == [True, False, False]
    out = [classify.apply(f, CLS) if f["ip"] in {"192.168.1.20"} else f for f in (c1, c2)]
    assert out == [c1, c2]
    assert out[0]["name"] == "postgres · a" and out[0]["kind"] == "container"
    assert classify.apply(host, CLS)["name"] == "Proxmox VM oder Container"


def test_source_names_keep_name_and_kind_but_get_purpose():
    for source, key in (("unifi", "unifi"), ("proxmox", "proxmox"), ("omada", "omada"), ("arp+unifi", "unifi")):
        f = {"name": "Mein Gerät", "kind": "network", "discoverySource": source, "extra": {key: {}}}
        out = classify.apply(f, CLS)
        assert out["name"] == "Mein Gerät" and out["kind"] == "network"
        assert out["purpose"] == "Zweck"


def test_discovery_source_variants():
    assert classify.has_source_name({"discoverySource": "docker+ki", "extra": None}) is True
    assert classify.has_source_name({"discoverySource": "", "extra": None}) is False
    assert classify.has_source_name({"discoverySource": "arp+ki"}) is False
    assert classify.apply({"name": "x", "kind": "other", "extra": None}, CLS)["name"] == "Proxmox VM oder Container"


def test_classify_run_skips_containers(monkeypatch):
    calls = []

    async def fake_chat(*a, **k):
        calls.append(a)
        raise AssertionError("no LLM call expected")

    monkeypatch.setattr(classify.llm_providers, "chat", fake_chat)
    by_ip, warnings = asyncio.run(classify.classify([_container("a", "p")], {}))
    assert by_ip == {} and warnings == [] and not calls
