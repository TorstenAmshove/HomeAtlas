"""Import boundaries of the reachability sources (ADR-0014)."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = ["traefik_probe", "exposure_files"]
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
