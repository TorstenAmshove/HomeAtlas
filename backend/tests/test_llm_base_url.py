import asyncio

import httpx
import pytest

from app import llm_providers as llm


def S(url):
    return {"ollamaBaseUrl": url}


def _field():
    return llm._BASE_URL_SETTING_FIELD["OLLAMA"][0]


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "http://127.0.0.1:11434/v1",
                                 "http://[::1]:11434/v1", "http://192.168.1.5:11434/v1",
                                 "http://ollama.lan:11434/v1"])
def test_allowed(url):
    assert llm.base_url_for("OLLAMA", {_field(): url}) == url


def test_default_ollama_url_ok():
    assert llm.base_url_for("OLLAMA", {}).startswith("http://localhost")


@pytest.mark.parametrize("url", ["http://169.254.169.254/v1", "http://0.0.0.0/v1", "http://224.0.0.1/v1",
                                 "http://[fe80::1]/v1", "ftp://x.lan/v1", "file:///etc/passwd",
                                 "http:///v1", "http://u:p@host.lan/v1", "http://host:99999/v1"])
def test_rejected(url):
    with pytest.raises(llm.ProviderError):
        llm.base_url_for("OLLAMA", {_field(): url})


def test_refresh_models_returns_message(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no request expected")
    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    ok, msg, models = asyncio.run(llm.refresh_models("OLLAMA", {_field(): "http://169.254.169.254/v1"}))
    assert ok is False and msg and models == []


def test_chat_raises_provider_error():
    with pytest.raises(llm.ProviderError):
        asyncio.run(llm.chat("OLLAMA", {_field(): "http://169.254.169.254/v1", "ollamaModel": "x"},
                             system_prompt="s", messages=[{"role": "user", "content": "hi"}]))


def test_test_connection_returns_failure():
    ok, msg, _ = asyncio.run(llm.test_connection("OLLAMA", {_field(): "http://169.254.169.254/v1",
                                                            "ollamaModel": "x"}))
    assert ok is False and msg
