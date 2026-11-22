"""Wiring of the live Home Assistant read tools in tools.py: account selection, error messages
without exceptions/secrets, MCP exposure, and the read/write import boundary."""
import ast
import asyncio
import json
from pathlib import Path

import pytest

from app import crypto, db, mcp_server, probe_auth, tools

APP = Path(__file__).resolve().parent.parent / "app"
NEW_TOOLS = ["get_ha_state", "get_ha_history", "get_ha_logbook", "get_ha_error_log"]


@pytest.fixture(autouse=True)
def _key(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)


def _ha_account(label="HA", url="http://ha.local:8123"):
    return db.create_account({"label": label, "category": "homeassistant", "url": url,
                              "secretEnc": crypto.encrypt("tok-secret"), "systemId": None})


def _call(name, args):
    return json.loads(asyncio.run(tools.dispatch(name, args)))


def test_no_ha_account(temp_db):
    for name in NEW_TOOLS:
        result = _call(name, {"entityId": "light.a"})
        assert "Home-Assistant-Zugang" in result["error"]


def test_multiple_accounts_need_account_id(temp_db):
    first, second = _ha_account("HA eins"), _ha_account("HA zwei")
    result = _call("get_ha_error_log", {})
    assert "accountId" in result["error"]
    assert first["id"] in result["error"] and "HA zwei" in result["error"]
    assert second["id"] in result["error"]


def test_unknown_or_wrong_category_account(temp_db):
    other = db.create_account({"label": "NAS", "category": "ssh", "url": "", "secretEnc": "", "systemId": None})
    _ha_account()
    assert "accountId" in _call("get_ha_error_log", {"accountId": "gibt-es-nicht"})["error"]
    assert "accountId" in _call("get_ha_error_log", {"accountId": other["id"]})["error"]


def test_single_account_is_used_and_secret_stays_out(temp_db, monkeypatch):
    account = _ha_account()
    seen = {}

    async def fake_log(url, acc):
        seen["url"] = url
        seen["secretEnc"] = acc.get("secretEnc")
        return {"ok": False, "error": "Home Assistant nicht erreichbar"}

    monkeypatch.setattr(probe_auth, "ha_error_log", fake_log)
    result = _call("get_ha_error_log", {})
    assert seen["url"] == "http://ha.local:8123" and seen["secretEnc"] != "tok-secret"
    assert result == {"error": "Home Assistant nicht erreichbar"}
    assert account["id"]


def test_history_and_logbook_forward_arguments(temp_db, monkeypatch):
    _ha_account()
    calls = {}

    async def fake_history(url, acc, entity_id, days, limit):
        calls["history"] = (entity_id, days, limit)
        return {"ok": True, "summary": {"onCount": 2}}

    async def fake_logbook(url, acc, entity_id, days, limit):
        calls["logbook"] = (entity_id, days, limit)
        return {"ok": True, "entries": []}

    monkeypatch.setattr(probe_auth, "ha_history", fake_history)
    monkeypatch.setattr(probe_auth, "ha_logbook", fake_logbook)
    assert _call("get_ha_history", {"entityId": "light.a", "days": 3})["summary"]["onCount"] == 2
    _call("get_ha_logbook", {"entityId": "cover.x", "limit": 5})
    assert calls["history"][:2] == ("light.a", 3) and calls["logbook"][0] == "cover.x"


def test_mcp_lists_new_tools():
    names = {t["name"] for t in tools.TOOL_DEFINITIONS}
    assert set(NEW_TOOLS) <= names
    assert mcp_server.tools is tools  # the MCP endpoint serves tools.TOOL_DEFINITIONS unchanged


def test_tools_imports_only_allowed_write_module():
    def imported(path: Path) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                found.update(a.name for a in node.names)
                if node.module:
                    found.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                found.update(a.name.split(".")[-1] for a in node.names)
        return found

    def writers(names: set[str]) -> set[str]:
        return {n for n in names if n.endswith("_admin") or n == "remote_admin"}

    assert writers(imported(APP / "tools.py")) <= {"switch_admin"}
    assert writers(imported(APP / "probe_auth.py")) == set()
    assert crypto  # keep the import used
