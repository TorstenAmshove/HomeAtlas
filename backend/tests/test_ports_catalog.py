from app import discovery, ports


def test_web_ports_are_in_catalog():
    assert set(discovery._WEB_PORTS) <= set(ports.SERVICES)
    assert 81 in ports.ALL_PORTS
