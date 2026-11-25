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
