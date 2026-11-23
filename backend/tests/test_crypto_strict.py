import pytest

from app import crypto


@pytest.fixture()
def keyfile(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    return tmp_path / "secret.key"


def test_strict_raises_on_wrong_key(keyfile, monkeypatch):
    token = crypto.encrypt("geheim-äöü")
    keyfile.unlink()
    monkeypatch.setattr(crypto, "_cached", None)
    with pytest.raises(crypto.SecretUnreadable) as exc:
        crypto.decrypt_strict(token)
    assert token not in str(exc.value)


def test_strict_raises_on_garbage_token(keyfile):
    with pytest.raises(crypto.SecretUnreadable):
        crypto.decrypt_strict("kein-token")


def test_strict_empty_token_returns_empty(keyfile):
    assert crypto.decrypt_strict("") == ""


def test_strict_roundtrip(keyfile):
    assert crypto.decrypt_strict(crypto.encrypt("pw")) == "pw"


def test_decrypt_stays_lenient(keyfile):
    assert crypto.decrypt("kein-token") == ""
