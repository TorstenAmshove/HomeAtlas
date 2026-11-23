"""Regression guard for the split of `db.py` into the package `db/` (ADR-0010).

(a) every name callers or tests used on `app.db` is still there, (b) the monkeypatched `DB_PATH`
reaches functions of every submodule, (c) `app.db._core` imports on its own, (d) no two submodules
define the same public name."""
import ast
import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

from app import db

EXPECTED_NAMES = ['DEFAULT_SETTINGS', '_ACCESS_LOG_KEEP', '_ADDED_COLUMNS', '_ASSIGNMENT_TARGET_TYPES', '_CONFIG_VERSION_KEEP_DEFAULT', '_DOC_VERSION_KEEP', '_DUPLICATE_KEY_MAX_GROUP', '_ERROR_EVENT_KEEP', '_INTERFACES_KEY', '_JSON_COLUMNS', '_NETWORK_RESOURCE_KINDS', '_PUBLIC_USER_COLUMNS', '_SCHEMA', '_SETTINGS_KEY', '_SYSTEM_FIELDS', '_alias_ip', '_assigned_account_ids', '_combine_interfaces', '_conn', '_dump', '_has_controller_origin', '_hostname_key', '_interfaces_of', '_ip_in_subnet', '_merge_extra', '_network_resource_key', '_new_id', '_now', '_record_interface', '_row', '_rows', '_self_reported_names', '_system_params', '_touch_alias_ip', '_union_interfaces', 'abandon_stale_scans', 'access_log_actions', 'add_chat_message', 'add_device_error_event', 'claim_totp_counter', 'count_assignments_by_account', 'count_error_events_by_system', 'count_users', 'create_account', 'create_api_token', 'create_chat', 'create_db_session', 'create_scan', 'create_system', 'create_user', 'delete_account', 'delete_api_token', 'delete_chat', 'delete_db_session', 'delete_doc_page', 'delete_system', 'delete_user', 'dismiss_duplicate', 'find_duplicate_candidates', 'find_system_by_alias', 'find_system_by_ip_and_hostname', 'find_system_by_key', 'find_system_by_mac', 'find_system_by_proxmox', 'find_system_by_unique_controller_ip', 'find_system_for_merge', 'finish_scan', 'get_account', 'get_chat', 'get_db_session', 'get_device_config_version', 'get_doc_page', 'get_doc_version', 'get_network_resource', 'get_scan', 'get_settings', 'get_system', 'get_user', 'get_user_by_username_raw', 'get_user_raw', 'init_db', 'invalidate_user_sessions', 'latest_scan', 'link_containers_to_host', 'list_access_log', 'list_account_assignments', 'list_accounts', 'list_aliases', 'list_api_tokens', 'list_assigned_accounts', 'list_chat_messages', 'list_chats', 'list_device_config_versions', 'list_device_error_events', 'list_doc_pages', 'list_doc_versions', 'list_monitor_events', 'list_monitored_systems', 'list_network_resources', 'list_probe_accounts', 'list_scans', 'list_systems', 'list_users', 'log_access', 'mark_systems_offline', 'merge_systems', 'record_monitor_state', 'redact_tool_messages', 'rename_chat', 'reset_doc_page', 'restore_doc_version', 'rewrite_doc_bodies', 'running_scan', 'save_device_config_version', 'set_account_assignments', 'set_doc_page_body', 'set_doc_page_manual', 'set_user_password', 'snapshot_doc_page', 'strip_probe_facts', 'sync_network_resources', 'touch_api_token', 'update_account', 'update_network_resource_manual', 'update_scan', 'update_settings', 'update_system', 'update_user', 'upsert_discovered_system', 'upsert_doc_page']
EXPECTED_NAMES += ["DB_PATH"]


def test_all_names_reexported():
    missing = [n for n in EXPECTED_NAMES if not hasattr(db, n)]
    assert missing == []


def test_every_submodule_writes_to_patched_path(temp_db, tmp_path):
    db_ = temp_db
    db_.update_settings({"homeName": "X"})
    assert db_.get_settings()["homeName"] == "X"
    uid = db_.create_user("u1", "h", "s", "MEMBER")
    assert db_.get_user(uid)["username"] == "u1"
    system = db_.create_system({"name": "Dev", "ip": "10.0.0.5", "kind": "other"})
    assert db_.get_system(system["id"])["name"] == "Dev"
    assert db_.list_network_resources() == []
    account = db_.create_account({"name": "A", "systemId": system["id"], "username": "x"})
    assert db_.get_account(account["id"])["id"] == account["id"]
    db_.upsert_doc_page("p", "t", "T", "body", "intro", 1)
    assert db_.get_doc_page("p")["title"] == "T"
    db_.save_device_config_version(system["id"], "l", "enc", "ssh")
    assert len(db_.list_device_config_versions(system["id"])) == 1
    db_.add_device_error_event(system["id"], "error", "boom")
    assert len(db_.list_device_error_events(system["id"])) == 1
    scan_id = db_.create_scan("10.0.0.0/24")
    assert db_.get_scan(scan_id)["id"] == scan_id
    db_.log_access("login")
    assert len(db_.list_access_log()) == 1
    db_.record_monitor_state(system["id"], "up", "")
    assert isinstance(db_.list_monitor_events(), list)
    chat = db_.create_chat("t")
    assert db_.get_chat(chat["id"])["id"] == chat["id"]
    assert (tmp_path / "test.db").exists()


def test_core_imports_standalone():
    out = subprocess.run([sys.executable, "-c", "import app.db._core"], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr


def test_no_duplicate_public_names():
    seen: dict[str, str] = {}
    for info in pkgutil.iter_modules(db.__path__):
        if info.name.startswith("_"):
            continue
        tree = ast.parse(Path(importlib.import_module(f"app.db.{info.name}").__file__).read_text())
        for node in tree.body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                if name.startswith("_"):
                    continue
                assert name not in seen, f"{name} defined in {seen[name]} and {info.name}"
                seen[name] = info.name
