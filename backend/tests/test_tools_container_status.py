"""get_container_status (ADR-0022): live local container status, read-only, allowlisted fields."""
import asyncio
import json
from pathlib import Path

import pytest

from app import docker_probe, mcp_server, tools


@pytest.fixture(autouse=True)
def _db(temp_db):
    return temp_db


def _row(name, service="", status="Up 1 hour", cid=None):
    return {"name": name, "image": "img:1", "state": "running", "status": status, "exitCode": None,
            "exitMeaning": None, "health": None, "since": "Up 1 hour", "composeProject": "p",
            "_service": service, "_id": cid or (name.encode().hex() + "0" * 64)[:64],
            "ports": [1], "Mounts": ["x"], "Command": "secret"}


def _live(monkeypatch, rows, ok=True, error=""):
    async def fake():
        return {"ok": ok, "error": error, "containers": rows}
    monkeypatch.setattr(docker_probe, "live_containers", fake)


def _call(arg=None):
    args = {} if arg is None else {"container": arg}
    return json.loads(asyncio.run(tools.dispatch("get_container_status", args)))


def test_by_name_and_empty_filter(monkeypatch):
    _live(monkeypatch, [_row("jellyfin", "jf"), _row("sonarr"), _row("jellyfin-db")])
    assert [c["name"] for c in _call()["containers"]] == ["jellyfin", "jellyfin-db", "sonarr"]
    assert [c["name"] for c in _call("JELLYFIN")["containers"]] == ["jellyfin"]  # exact beats substring
    assert [c["name"] for c in _call("jf")["containers"]] == ["jellyfin"]  # compose service
    assert [c["name"] for c in _call("sonar")["containers"]] == ["sonarr"]  # substring


def test_resolves_inventory_id_to_name(monkeypatch):
    import app.db as db
    _live(monkeypatch, [_row("jellyfin", cid="f" * 64), _row("other")])
    monkeypatch.setattr(db, "get_system", lambda i: {"name": "x · y", "extra": {"docker": {"containerId": "f" * 64}}}
                        if i == "sys-1" else None)
    assert [c["name"] for c in _call("sys-1")["containers"]] == ["jellyfin"]


def test_limit_50_with_truncation_note(monkeypatch):
    _live(monkeypatch, [_row(f"c{i:02d}") for i in range(60)])
    out = _call()
    assert len(out["containers"]) == 50 and out["count"] == 60 and out["truncated"] is True and "gekürzt" in out["note"]


def test_no_socket_message(monkeypatch):
    _live(monkeypatch, [], ok=False, error="Docker-Socket nicht eingebunden – Live-Status nicht verfügbar")
    assert "nicht eingebunden" in _call()["error"]


def test_filter_no_match_and_bad_type(monkeypatch):
    _live(monkeypatch, [_row("a")])
    assert _call("zzz")["count"] == 0 and "Kein Container" in _call("zzz")["note"]
    assert "Text" in json.loads(asyncio.run(tools.dispatch("get_container_status", {"container": 5})))["error"]
    assert "zu lang" in _call("x" * 101)["error"]


def test_no_extra_fields_in_tool_output(monkeypatch):
    _live(monkeypatch, [_row("a", "svc")])
    c = _call()["containers"][0]
    assert set(c) == set(tools._CONTAINER_FIELDS)


def test_registered_for_chat_and_mcp():
    assert "get_container_status" in {d["name"] for d in tools.TOOL_DEFINITIONS}
    assert mcp_server.tools is tools


def test_no_write_import():
    for f in ("tools.py", "docker_probe.py"):
        src = (Path(tools.__file__).parent / f).read_text(encoding="utf-8")
        assert "import docker_admin" not in src and "remote_admin" not in src.replace("remote_admin.py", "")
        assert "docker_admin," not in src


def test_prompt_rule_in_chat_system():
    out = tools.build_system_prompt({})
    assert "get_container_status" in out and "der Admin erledigen muss" in out
    assert "Behaupte nie, etwas ausgeführt zu haben" in out
    # a custom override replaces the whole base prompt, as for every CHAT_SYSTEM rule
    assert "get_container_status" not in tools.build_system_prompt({"systemPromptOverride": "x"})


def test_mcp_has_no_prompts():
    src = (Path(mcp_server.__file__)).read_text(encoding="utf-8")
    assert "list_prompts" not in src and "prompts" not in src.replace("tools.prompts", "")
