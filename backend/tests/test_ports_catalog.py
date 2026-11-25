from app import discovery, ports


def test_web_ports_are_in_catalog():
    assert set(discovery._WEB_PORTS) <= set(ports.SERVICES)
    assert 81 in ports.ALL_PORTS


def _kind_model(open_ports):
    hint = ports.hint_from_ports(open_ports)
    return (hint[0], hint[1]) if hint else None


def test_home_assistant_beats_sonos():
    # Home Assistant opens 1400 itself for its Sonos integration's event callbacks.
    assert _kind_model([22, 80, 111, 1400, 8123]) == ("smarthome", "Home Assistant")


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "product_port,expected",
    [
        (8123, ("smarthome", "Home Assistant")),
        (32400, ("server", "Plex")),
        (8096, ("server", "Jellyfin")),
        (8006, ("server", "Proxmox VE")),
        (11434, ("server", "Ollama")),
    ],
)
def test_product_ports_beat_sonos(product_port, expected):
    assert _kind_model([1400, product_port]) == expected


def test_sonos_still_detected():
    assert _kind_model([1400]) == ("media", "Sonos")
    assert _kind_model([80, 1400]) == ("media", "Sonos")


def test_printer_and_camera_beat_sonos():
    assert _kind_model([1400, 9100])[0] == "printer"
    assert _kind_model([1400, 554])[0] == "camera"


@pytest.mark.parametrize("lower", [8008, 5001, 1883])
def test_sonos_beats_lower_hints(lower):
    assert _kind_model([lower, 1400]) == ("media", "Sonos")


def test_no_ports_no_hint():
    assert ports.hint_from_ports([]) is None
