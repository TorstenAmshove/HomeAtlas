"""The running release version comes from the HOMEATLAS_VERSION build arg / env."""
import pytest

from app.version import app_version


def test_app_version_default_and_env(monkeypatch):
    monkeypatch.delenv("HOMEATLAS_VERSION", raising=False)
    assert app_version() == "dev"
    monkeypatch.setenv("HOMEATLAS_VERSION", "1.2.3")
    assert app_version() == "1.2.3"
    monkeypatch.setenv("HOMEATLAS_VERSION", "  1.2.3 ")
    assert app_version() == "1.2.3"


@pytest.mark.parametrize("raw", ["", "   "])
def test_app_version_blank_is_dev(monkeypatch, raw):
    monkeypatch.setenv("HOMEATLAS_VERSION", raw)
    assert app_version() == "dev"
