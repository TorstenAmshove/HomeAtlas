"""Model list refresh (pagination, Gemini key in header) and the providerModelCache lifecycle."""
import asyncio

import httpx
import pytest

from app import crypto, db, llm_providers, model_catalog
from app.routes import settings as settings_routes

KEY = "test-key-not-a-secret-1"


@pytest.fixture()
def keyed(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    return temp_db


def _mock_http(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(llm_providers.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw))
    return seen


def _refresh(provider, settings):
    return asyncio.run(llm_providers.refresh_models(provider, settings))


def _gemini_settings():
    return {"geminiApiKey": crypto.encrypt(KEY)}


def _claude_settings():
    return {"claudeApiKey": crypto.encrypt(KEY)}


def _gm(name, methods=("generateContent",)):
    return {"name": f"models/{name}", "displayName": name, "supportedGenerationMethods": list(methods)}


# --- Gemini key only in header ------------------------------------------------------------------

def test_gemini_refresh_key_in_header_only(keyed, monkeypatch):
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"models": [_gm("g1")]}))
    ok, _, models = _refresh("GEMINI", _gemini_settings())
    assert ok and [m["id"] for m in models] == ["g1"]
    assert seen[0].headers["x-goog-api-key"] == KEY
    assert "key" not in seen[0].url.params and KEY not in str(seen[0].url)


def test_gemini_chat_key_in_header_only(keyed, monkeypatch):
    body = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = asyncio.run(llm_providers._chat_gemini(KEY, "g1", "sys", [{"role": "user", "content": "hi"}], None))
    assert result.text == "OK"
    assert seen[0].headers["x-goog-api-key"] == KEY
    assert "key" not in seen[0].url.params and KEY not in str(seen[0].url)


def test_gemini_error_text_has_no_key(keyed, monkeypatch):
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(403, text="API key not valid"))
    ok, message, models = _refresh("GEMINI", _gemini_settings())
    assert not ok and models == [] and KEY not in message and KEY not in str(seen[0].url)


# --- pagination, order, duplicates --------------------------------------------------------------

def test_claude_refresh_paginates(keyed, monkeypatch):
    def handler(r):
        if r.url.params.get("after_id") == "b":
            return httpx.Response(200, json={"data": [{"id": "c"}], "has_more": False})
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}], "has_more": True, "last_id": "b"})

    seen = _mock_http(monkeypatch, handler)
    ok, message, models = _refresh("CLAUDE", _claude_settings())
    assert ok and [m["id"] for m in models] == ["a", "b", "c"]
    assert seen[0].url.params["limit"] == "1000" and "after_id" not in seen[0].url.params
    assert len(seen) == 2 and "gekürzt" not in message


def test_gemini_refresh_paginates_and_filters_each_page(keyed, monkeypatch):
    def handler(r):
        if r.url.params.get("pageToken") == "t2":
            return httpx.Response(200, json={"models": [_gm("g3"), _gm("emb", ("embedContent",))]})
        return httpx.Response(200, json={"models": [_gm("g2"), _gm("emb1", ("embedContent",))],
                                         "nextPageToken": "t2"})

    seen = _mock_http(monkeypatch, handler)
    ok, _, models = _refresh("GEMINI", _gemini_settings())
    assert ok and [m["id"] for m in models] == ["g2", "g3"]
    assert seen[0].url.params["pageSize"] == "1000"


def test_pagination_stops_at_10_pages_and_says_so(keyed, monkeypatch):
    counter = iter(range(100))

    def handler(r):
        i = next(counter)
        return httpx.Response(200, json={"data": [{"id": f"m{i:02d}"}], "has_more": True, "last_id": f"m{i:02d}"})

    seen = _mock_http(monkeypatch, handler)
    ok, message, models = _refresh("CLAUDE", _claude_settings())
    assert ok and len(seen) == 10 and len(models) == 10 and "gekürzt" in message


def test_pagination_has_more_without_last_id_stops(keyed, monkeypatch):
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "a"}], "has_more": True}))
    ok, _, models = _refresh("CLAUDE", _claude_settings())
    assert ok and len(seen) == 1 and len(models) == 1


def test_pagination_repeated_token_stops(keyed, monkeypatch):
    body = {"models": [_gm("g1")], "nextPageToken": "same"}
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    ok, _, models = _refresh("GEMINI", _gemini_settings())
    assert ok and len(seen) == 2 and len(models) == 1


def test_empty_page_with_more_continues(keyed, monkeypatch):
    def handler(r):
        if r.url.params.get("after_id"):
            return httpx.Response(200, json={"data": [{"id": "a"}], "has_more": False})
        return httpx.Response(200, json={"data": [], "has_more": True, "last_id": "x"})

    _mock_http(monkeypatch, handler)
    ok, _, models = _refresh("CLAUDE", _claude_settings())
    assert ok and [m["id"] for m in models] == ["a"]


def test_pagination_error_on_page_two_returns_error_and_no_models(keyed, monkeypatch):
    def handler(r):
        if r.url.params.get("after_id"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"data": [{"id": "a"}], "has_more": True, "last_id": "a"})

    _mock_http(monkeypatch, handler)
    ok, message, models = _refresh("CLAUDE", _claude_settings())
    assert not ok and models == [] and "500" in message


def test_duplicates_removed_and_sorted_by_id(keyed, monkeypatch):
    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "z"}, {"id": "a"}, {"id": "z"}]}))
    ok, _, models = _refresh("OPENAI", {"openAiApiKey": crypto.encrypt(KEY)})
    assert ok and [m["id"] for m in models] == ["a", "z"]


def test_resolve_fallback_follows_live_list_order():
    live = ["aaa", "mmm", "zzz"]
    assert model_catalog.resolve("CLAUDE", model_catalog.AUTO_MODEL_ID, "CHAT", live) == "aaa"
    assert model_catalog.resolve("CLAUDE", model_catalog.AUTO_MODEL_ID, "ANALYSIS", live) == "zzz"


# --- cache lifecycle ----------------------------------------------------------------------------

def _seed(provider="CLAUDE", **extra):
    db.update_settings({
        f"{provider.lower()}ApiKey": crypto.encrypt(KEY),
        "providerModelCache": {provider: {"models": [{"id": "m1", "label": "m1"}]},
                               "OPENAI": {"models": [{"id": "o1", "label": "o1"}]}},
        **extra,
    })


def _patch(body):
    patch = settings_routes.SettingsPatch(**body)
    return asyncio.run(settings_routes.update_settings(patch, {}))["settings"]


def test_key_change_drops_only_that_providers_cache(keyed):
    _seed()
    s = _patch({"claudeApiKey": "another-key-value"})
    assert "CLAUDE" not in s["providerModelCache"] and "OPENAI" in s["providerModelCache"]


def test_base_url_change_drops_cache(keyed):
    _seed()
    s = _patch({"claudeBaseUrl": "http://proxy.lan:9000"})
    assert "CLAUDE" not in s["providerModelCache"]


def test_clear_secret_drops_cache(keyed):
    _seed()
    s = _patch({"clearSecrets": ["claudeApiKey"]})
    assert "CLAUDE" not in s["providerModelCache"]


def test_patch_keeps_cache_when_key_and_url_unchanged(keyed):
    _seed()
    s = _patch({"claudeApiKey": settings_routes._MASK, "homeName": "X"})
    assert s["providerModelCache"]["CLAUDE"]["models"][0]["id"] == "m1"
    s = _patch({"claudeApiKey": KEY})  # same key sent again in plaintext
    assert "CLAUDE" in s["providerModelCache"]


def test_patch_ignores_cache_in_body(keyed):
    _seed()
    s = _patch({"providerModelCache": {"CLAUDE": {"models": [{"id": "evil", "label": "evil"}]}}})
    assert s["providerModelCache"]["CLAUDE"]["models"][0]["id"] == "m1"


def test_unreadable_old_key_drops_cache(keyed):
    db.update_settings({"claudeApiKey": "enc:garbage-not-decryptable",
                        "providerModelCache": {"CLAUDE": {"models": [{"id": "m1", "label": "m1"}]}}})
    s = _patch({"claudeApiKey": KEY})
    assert "CLAUDE" not in s["providerModelCache"]


def test_keyless_provider_ollama_keeps_cache(keyed):
    db.update_settings({"providerModelCache": {"OLLAMA": {"models": [{"id": "l1", "label": "l1"}]}}})
    s = _patch({"homeName": "X"})
    assert "OLLAMA" in s["providerModelCache"]


def test_default_url_equals_explicit_default_keeps_cache(keyed):
    _seed()
    s = _patch({"claudeBaseUrl": model_catalog.DEFAULT_CLAUDE_BASE_URL + "/"})
    assert "CLAUDE" in s["providerModelCache"]


def _refresh_route(body):
    return asyncio.run(settings_routes.refresh_llm_models(settings_routes.ProviderBody(**body), {}))


def test_refresh_with_unsaved_key_not_persisted(keyed, monkeypatch):
    _seed()
    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "new"}]}))
    r = _refresh_route({"provider": "CLAUDE", "settings": {"claudeApiKey": "unsaved-key-value"}})
    assert r["ok"] and r["persisted"] is False and r["models"][0]["id"] == "new"
    assert "Speichern" in r["message"]
    assert db.get_settings()["providerModelCache"]["CLAUDE"]["models"][0]["id"] == "m1"


def test_refresh_with_masked_key_persisted(keyed, monkeypatch):
    _seed()
    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "new"}]}))
    r = _refresh_route({"provider": "CLAUDE", "settings": {"claudeApiKey": settings_routes._MASK}})
    assert r["persisted"] is True
    assert db.get_settings()["providerModelCache"]["CLAUDE"]["models"][0]["id"] == "new"


def test_refresh_with_changed_url_not_persisted(keyed, monkeypatch):
    _seed()
    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "new"}]}))
    r = _refresh_route({"provider": "CLAUDE", "settings": {"claudeBaseUrl": "http://other.lan"}})
    assert r["ok"] and r["persisted"] is False
    assert db.get_settings()["providerModelCache"]["CLAUDE"]["models"][0]["id"] == "m1"
