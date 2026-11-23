"""The password policy (`security.check_password`) must hold on every path that sets a password:
API, ADMIN_PASSWORD bootstrap and the CLI reset."""
import logging

import pytest

from app import auth, db, reset_password, security

STRONG = "Dev-Passwort-2024"


def _bootstrap(monkeypatch, password, username="admin"):
    monkeypatch.setenv("ADMIN_USERNAME", username)
    if password is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", password)
    return auth.ensure_admin_bootstrapped()


def test_weak_admin_password_falls_back_to_generated(temp_db, monkeypatch):
    result = _bootstrap(monkeypatch, "devpass123")
    assert result.password and result.reason
    assert auth.verify_login("admin", "devpass123") is None
    assert auth.verify_login("admin", result.password) is not None
    security.check_password(result.password, "admin")


def test_strong_admin_password_is_used_verbatim(temp_db, monkeypatch):
    result = _bootstrap(monkeypatch, STRONG)
    assert result.password is None and result.reason is None
    assert auth.verify_login("admin", STRONG) is not None


def test_admin_password_containing_username_is_rejected(temp_db, monkeypatch):
    result = _bootstrap(monkeypatch, "Hausadmin-Passwort-1", username="hausadmin")
    assert result.password and result.reason
    assert auth.verify_login("hausadmin", "Hausadmin-Passwort-1") is None


def test_empty_admin_password_generates(temp_db, monkeypatch):
    result = _bootstrap(monkeypatch, "")
    assert result.password and result.reason is None
    assert auth.verify_login("admin", result.password) is not None


def test_existing_user_untouched_even_with_weak_env(temp_db, monkeypatch):
    assert _bootstrap(monkeypatch, STRONG).password is None
    result = _bootstrap(monkeypatch, "devpass123")
    assert result.password is None and result.reason is None
    assert auth.verify_login("admin", STRONG) is not None


def test_weak_password_is_never_logged(temp_db, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        result = _bootstrap(monkeypatch, "devpass123")
    assert result.reason
    assert "devpass123" not in caplog.text
    assert "devpass123" not in result.reason


@pytest.mark.parametrize("username", ["admin", "Mond", "Eiche", "Sonne", "Granit"])
def test_generated_password_passes_policy_for_every_word(username):
    # Words may be part of the username; the generator must re-roll instead of returning a
    # password the policy rejects.
    for _ in range(300):
        security.check_password(auth._generate_password(username), username)


def test_documented_example_password_passes():
    security.check_password(STRONG, "admin")


def _cli(*args):
    return reset_password.main(list(args))


def test_cli_rejects_weak_password_for_existing_user(temp_db, capsys):
    _cli("alice", STRONG)
    before = db.get_user_by_username_raw("alice")["passwordHash"]
    for weak in ("devpass1", "devpass123"):
        assert _cli("alice", weak) == 2
        assert db.get_user_by_username_raw("alice")["passwordHash"] == before
        assert capsys.readouterr().err.strip()


def test_cli_rejects_weak_password_for_new_user(temp_db):
    assert _cli("bob", "devpass123") == 2
    assert db.get_user_by_username_raw("bob") is None


def test_cli_rejects_password_with_username(temp_db):
    assert _cli("carolin", "Carolin-Passwort-1") == 2
    assert db.get_user_by_username_raw("carolin") is None


def test_cli_accepts_valid_password(temp_db):
    assert _cli("alice", STRONG) == 0
    assert db.get_user_by_username_raw("alice") is not None


def test_cli_reset_mfa_without_password_skips_check(temp_db):
    _cli("alice", STRONG)
    assert _cli("alice", "--reset-mfa") == 0


def test_cli_weak_password_with_reset_mfa_changes_nothing(temp_db):
    _cli("alice", STRONG)
    user = db.get_user_by_username_raw("alice")
    db.update_user(user["id"], {"totpSecretEnc": "x", "totpEnabled": True})
    assert _cli("alice", "devpass123", "--reset-mfa") == 2
    after = db.get_user_by_username_raw("alice")
    assert after["totpEnabled"]
    assert after["passwordHash"] == user["passwordHash"]


def test_cli_ambiguous_legacy_name_aborts(temp_db, capsys):
    for name in ("anna", "ANNA"):
        db.create_user(name, "h", "s", auth.ROLE_ADMIN)
    assert _cli("Anna", "Korrekt-Pferd-Batterie-9") == 1
    assert "mehrdeutig" in capsys.readouterr().err


def test_cli_new_user_name_is_validated(temp_db):
    assert _cli("a b", "Korrekt-Pferd-Batterie-9") == 2
    assert db.get_user_by_username_raw("a b") is None
