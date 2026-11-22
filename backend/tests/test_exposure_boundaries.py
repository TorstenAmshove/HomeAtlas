"""Import boundaries of the reachability sources (ADR-0014)."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = ["traefik_probe", "exposure_files", "unifi_classic_probe", "cloudflare_probe", "public_dns",
           "firewall_unifi"]
FORBIDDEN_IN_SOURCES = {"remote_admin", "docker_admin", "proxmox_admin", "switch_admin", "probe_auth", "tools"}


def _imports(name: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse((APP / f"{name}.py").read_text())):
        if isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
    return found


def test_sources_import_no_writing_module():
    for name in SOURCES:
        assert not _imports(name) & FORBIDDEN_IN_SOURCES, name


def test_tools_does_not_import_sources():
    assert not _imports("tools") & set(SOURCES)


def test_traefik_probe_only_uses_get_and_fixed_paths():
    src = (APP / "traefik_probe.py").read_text()
    for verb in ("client.post", "client.put", "client.delete", "client.patch", "client.request"):
        assert verb not in src
    assert src.count("_get_list(client, base_url, \"/api/") == 3


def test_exposure_files_runs_only_the_fixed_command_table():
    src = (APP / "exposure_files.py").read_text()
    assert src.count("connection.run(") == 1 and "connection.run(command," in src
    assert "command = _FILE_COMMANDS.get(source)" in src
    for verb in ("create_process", "start_sftp_client", "open_session", "subprocess"):
        assert verb not in src


def test_unifi_classic_probe_is_get_only_with_key():
    src = (APP / "unifi_classic_probe.py").read_text()
    for verb in ("client.post", "client.put", "client.delete", "client.patch", "client.request"):
        assert verb not in src
    assert "/api/auth/login" not in src.replace("no login", "") .split('"""', 2)[2]
    assert "follow_redirects=False" in src and "unifi_live" not in src.split('"""', 2)[2]


def test_outside_sources_only_use_get():
    for name in ("cloudflare_probe", "public_dns"):
        src = (APP / f"{name}.py").read_text()
        for verb in ("client.post", "client.put", "client.delete", "client.patch", "client.request"):
            assert verb not in src, (name, verb)
    assert 'cfd_tunnel/' not in (APP / "cloudflare_probe.py").read_text()  # no per-tunnel (token) endpoint
