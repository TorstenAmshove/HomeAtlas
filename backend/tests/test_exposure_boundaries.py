"""Import boundaries of the reachability sources (ADR-0014)."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = ["traefik_probe"]
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
