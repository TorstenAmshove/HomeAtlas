"""Import and verb boundaries of the firewall sources (ADR-0017)."""
from pathlib import Path

from test_exposure_boundaries import APP, FORBIDDEN_IN_SOURCES, _imports

ROOT = Path(__file__).resolve().parents[2]


def test_firewall_unifi_imports_no_admin_or_live_module():
    assert not _imports("firewall_unifi") & (FORBIDDEN_IN_SOURCES | {"unifi_live", "unifi_classic_probe"})


def test_firewall_unifi_is_get_only_with_key():
    src = (APP / "firewall_unifi.py").read_text()
    for verb in ("client.post", "client.put", "client.delete", "client.patch", "client.request"):
        assert verb not in src
    assert "follow_redirects=False" in src and src.count("client.get(") == 1


def test_pipeline_imports_no_writing_module():
    assert not _imports("pipeline") & {"remote_admin", "docker_admin", "proxmox_admin", "switch_admin"}


def test_tools_does_not_import_firewall_sources():
    assert not _imports("tools") & {"firewall_unifi", "firewall_nft"}
    assert not _imports("mcp_server") & {"firewall_unifi", "firewall_nft"}


def test_constitution_links_no_superseded_adr():
    text = (ROOT / "docs/specs/constitution.md").read_text()
    assert "0016-unifi-scan-nur-mit-api-key" not in text
    assert "0017-firewall-quellen-und-pfadbewertung" not in text
    assert "0018-wan-status-und-lesepfade" not in text
    assert "0019-firewall-zonen-subnetze" in text




def test_firewall_nft_runs_only_the_fixed_command():
    src = (APP / "firewall_nft.py").read_text()
    assert src.count("connection.run(") == 1 and "connection.run(_NFT_COMMAND," in src
    assert _imports("firewall_nft").isdisjoint(FORBIDDEN_IN_SOURCES | {"remote_admin", "probe_auth"})
    for verb in ("create_process", "start_sftp_client", "open_session", "subprocess"):
        assert verb not in src


def test_firewall_eval_is_pure():
    assert _imports("firewall_eval") <= {"__future__", "annotations", "ipaddress", "re"}
