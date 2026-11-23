"""Existing `sshkey` accounts keep working for read-only SSH probing (#217): the stored key is
decrypted, loaded with the stored passphrase (or none), and the account's username is used."""
import asyncio

import asyncssh
import pytest

from app import crypto, probe_auth


class _Result:
    stdout = "Linux nas 6.1\n"


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, command, **kwargs):
        return _Result()


@pytest.fixture()
def keyed(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)


@pytest.mark.parametrize("passphrase, expected", [("", None), ("geheim", "geheim")])
def test_probe_ssh_uses_sshkey_account(keyed, monkeypatch, passphrase, expected):
    seen = {}

    def fake_import(pem, phrase=None):
        seen["pem"], seen["passphrase"] = pem, phrase
        return "KEY"

    def fake_connect(**kwargs):
        seen["connect"] = kwargs
        return _Conn()

    monkeypatch.setattr(asyncssh, "import_private_key", fake_import)
    monkeypatch.setattr(asyncssh, "connect", fake_connect)
    account = {"category": "sshkey", "username": "svc", "port": 2222,
               "secretEnc": crypto.encrypt("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"),
               "passphraseEnc": crypto.encrypt(passphrase)}
    result = asyncio.run(probe_auth.probe_ssh("192.0.2.9", account))
    assert result["ok"] is True
    assert seen["passphrase"] == expected and "PRIVATE KEY" in seen["pem"]
    assert seen["connect"]["username"] == "svc" and seen["connect"]["port"] == 2222
    assert seen["connect"]["client_keys"] == ["KEY"] and seen["connect"]["password"] is None
