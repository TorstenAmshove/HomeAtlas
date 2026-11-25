from app import docs


def _sys(sid, name, kind="server", conn=None, mac=""):
    extra = {"unifi": {"connection": conn}} if conn else {}
    return {"id": sid, "name": name, "kind": kind, "ip": "", "mac": mac, "vendor": "", "model": "",
            "location": "", "importance": "normal", "parentId": None, "url": "", "lastSeen": "", "extra": extra,
            "services": [], "status": "online", "notes": ""}


def _render(*systems):
    by_id = {s["id"]: s for s in systems}
    return docs._device_details(list(systems), by_id, {})


def _wired(device, port):
    return {"type": "wired", "systemId": device, "deviceMac": "aa:bb:cc:00:00:10", "port": port,
            "site": "default", "accountId": "acc"}


def test_wired_and_wifi_lines_and_port_list():
    sw, ap = _sys("sw", "Switch Flur", "switch"), _sys("ap", "AP Wohnzimmer", "accesspoint")
    tv = _sys("tv", "Fernseher", conn=_wired("sw", 5))
    nas = _sys("nas", "NAS | Keller", conn=_wired("sw", 2))
    box = _sys("box", "Box", conn=_wired("sw", 5))
    phone = _sys("ph", "Handy", conn={"type": "wifi", "systemId": "ap", "ssid": "Zuhause", "deviceMac": "x"})
    text = _render(sw, ap, tv, nas, box, phone)
    assert "- **Angeschlossen an:** Switch Flur, Port 5" in text
    assert "- **Verbunden mit:** AP Wohnzimmer (WLAN Zuhause)" in text
    assert text.index("Port 2: NAS \\| Keller") < text.index("Port 5: Box") < text.index("Port 5: Fernseher")
    assert "  - WLAN Zuhause: Handy" in text


def test_wifi_without_device_and_missing_switch():
    phone = _sys("ph", "Handy", conn={"type": "wifi", "ssid": "Zuhause", "deviceMac": "x"})
    gone = _sys("tv", "TV", conn=_wired("deleted", 3))
    text = _render(phone, gone)
    assert "- **Verbunden mit:** WLAN Zuhause" in text and "Angeschlossen an" not in text


def test_no_connection_no_line():
    assert "Angeschlossen" not in _render(_sys("a", "A")) and "Verbunden mit" not in _render(_sys("a", "A"))


def test_docs_show_names_not_ids():
    sw = _sys("switch-id-123", "Switch", "switch", mac="aa:bb:cc:00:00:10")
    tv = _sys("tv-id-456", "TV", conn=_wired("switch-id-123", 1))
    text = _render(sw, tv)
    assert "switch-id-123" not in text.replace("`aa:bb:cc:00:00:10`", "") and "tv-id-456" not in text
    assert "deviceMac" not in text


def _ports(*ports):
    return {"accountId": "acc", "site": "default", "ports": list(ports)}


def _port(n, name="", native=None, mode="", excluded=()):
    return {"port": n, "name": name, "profile": "",
            "native": native or {"vlan": None, "name": "", "known": True},
            "tagged": {"mode": mode, "vlans": [], "excluded": list(excluded)}}


def test_docs_switch_port_table():
    sw = _sys("sw", "Switch Flur", "switch")
    sw["extra"] = {"unifi": {"ports": _ports(
        _port(1, "Büro | PC", {"vlan": 10, "name": "Default", "known": True}, "all"),
        _port(2, "", {"vlan": 20, "name": "IoT", "known": True}, "none"),
        _port(3, "", {"vlan": None, "name": "", "known": False}, "all",
              [{"vlan": 30, "name": "Gäste"}, {"vlan": None, "name": ""}]),
        _port(4, "Trunk", mode="custom"))}}
    tv = _sys("tv", "Fernseher", conn=_wired("sw", 1))
    text = _render(sw, tv)
    assert "| Port | Name | Nativ | Tagged | Angeschlossenes Gerät |" in text
    assert "| 1 | Büro \\| PC | VLAN 10 *Default* | alle | Fernseher |" in text
    assert "| 2 | – | VLAN 20 *IoT* | keine | – |" in text
    assert "| 3 | – | unbekanntes Netz | alle außer VLAN 30 *Gäste*, unbekanntes Netz | – |" in text
    assert "| 4 | Trunk | – | benutzerdefiniert (Liste nicht gelesen) | – |" in text


def test_docs_switch_without_ports_renders_no_table():
    assert "Ports und VLANs" not in _render(_sys("sw", "Switch", "switch"))
    legacy = _sys("sw", "Switch", "switch")
    legacy["extra"] = {"unifi": {"ports": "kaputt"}}
    assert "Ports und VLANs" not in _render(legacy)
