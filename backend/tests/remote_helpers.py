"""Shared helper for the switching tests. Plain function, no pytest magic."""
from __future__ import annotations

from app import crypto


def isolate_crypto(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
