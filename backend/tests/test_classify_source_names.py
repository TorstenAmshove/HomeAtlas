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


def _self_reported(source, **extra):
    return {"name": "Wohnzimmer", "kind": "other", "discoverySource": "ping/arp+ssdp",
            "extra": {"nameSource": source, **extra}}


def test_upnp_name_kept_kind_updated():
    out = classify.apply(_self_reported("upnp"), CLS)
    assert out["name"] == "Wohnzimmer" and out["kind"] == "vm"
    assert out["purpose"] == "Zweck" and out["discoverySource"].endswith("+ki")
    assert out["extra"]["aiConfidence"] == "high"


def test_mdns_name_kept_kind_updated():
    out = classify.apply(_self_reported("mdns"), CLS)
    assert out["name"] == "Wohnzimmer" and out["kind"] == "vm"
    assert out["purpose"] == "Zweck" and out["discoverySource"].endswith("+ki")


def test_shelly_app_name_kept():
    out = classify.apply(_self_reported("shelly"), CLS)
    assert out["name"] == "Wohnzimmer" and out["kind"] == "vm"


def test_hostname_title_vendor_names_still_replaced():
    for source in ("hostname", "title", "vendor", "ip"):
        out = classify.apply(_self_reported(source), CLS)
        assert out["name"] == "Proxmox VM oder Container"


def test_missing_or_unknown_name_source_unchanged():
    for f in ({"name": "x", "kind": "other", "extra": {}},
              {"name": "x", "kind": "other", "extra": None},
              {"name": "x", "kind": "other", "extra": {"nameSource": "wat"}}):
        assert classify.apply(f, CLS)["name"] == "Proxmox VM oder Container"


def test_source_plus_self_reported_keeps_name_and_kind():
    f = {"name": "Mein AP", "kind": "network", "discoverySource": "arp+unifi",
         "extra": {"unifi": {}, "nameSource": "upnp"}}
    out = classify.apply(f, CLS)
    assert out["name"] == "Mein AP" and out["kind"] == "network"


def test_container_with_name_source_untouched():
    c = _container("x", "p")
    c["extra"]["nameSource"] = "mdns"
    assert classify.apply(c, CLS) == c


def test_empty_ai_name_never_overwrites():
    out = classify.apply(_self_reported("hostname"), {**CLS, "name": ""})
    assert out["name"] == "Wohnzimmer"


def test_force_only_skips_need_test():
    confident = {"ip": "192.168.1.5", "kind": "router", "purpose": "x", "docUrl": "u",
                 "openPorts": [80], "extra": {}}
    assert not classify.needs_classification(confident)
    calls = []

    async def fake_chat(*a, **k):
        calls.append(1)
        raise classify.llm_providers.ProviderError("nope")

    orig, orig_cfg = classify.llm_providers.chat, classify.llm_providers.is_configured
    classify.llm_providers.chat = fake_chat
    classify.llm_providers.is_configured = lambda *a: True
    try:
        asyncio.run(classify.classify([confident], {}))
        assert calls == []
        asyncio.run(classify.classify([confident], {}, force=True))
        assert calls == [1]
        asyncio.run(classify.classify([_container("c", "p"), {"ip": "1.1.1.1", "extra": {}}], {}, force=True))
        assert calls == [1]
    finally:
        classify.llm_providers.chat, classify.llm_providers.is_configured = orig, orig_cfg


def _system(**kw):
    return {"ip": "192.168.1.5", "name": "Alt", "kind": "other", "confirmed": 0, "purpose": "",
            "docUrl": "", "docLink": "", "vendor": "", "model": "", "descriptionMd": "",
            "importance": "normal", "discoverySource": "arp", "openPorts": [80], "extra": {}, **kw}


def test_apply_to_system_unconfirmed_and_source_name():
    patch = classify.apply_to_system(_system(), CLS)
    assert patch["kind"] == "vm" and patch["purpose"] == "Zweck"
    assert patch["extra"]["aiConfidence"] == "high" and patch["discoverySource"] == "arp+ki"
    patch = classify.apply_to_system(_system(discoverySource="unifi", extra={"unifi": {}}), CLS)
    assert "kind" not in patch and "name" not in patch and patch["purpose"] == "Zweck"
    patch = classify.apply_to_system(_system(extra={"nameSource": "mdns"}), CLS)
    assert "name" not in patch and patch["kind"] == "vm"


def test_apply_to_system_confirmed_fills_only_empty():
    patch = classify.apply_to_system(_system(confirmed=1, purpose="Mein Zweck"),
                                     {**CLS, "vendor": "V", "docUrl": "https://d.example"})
    assert patch["vendor"] == "V" and patch["docUrl"] == "https://d.example"
    assert not {"kind", "name", "importance", "purpose", "confirmed"} & set(patch)
    patch = classify.apply_to_system(_system(confirmed=1, docLink="https://m.example"),
                                     {**CLS, "docUrl": "https://d.example"})
    assert "docUrl" not in patch


def test_apply_to_system_container_empty():
    assert classify.apply_to_system(_system(extra={"docker": {}}), CLS) == {}
