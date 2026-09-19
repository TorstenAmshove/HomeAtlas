"""IEEE OUI registry download and cache behavior."""
import asyncio

import httpx

from app import oui


def test_refresh_identifies_homeatlas_to_ieee(monkeypatch, tmp_path):
    registry = "".join(
        f"MA-L,{assignment:06X},Vendor {assignment},Address\n"
        for assignment in range(1000)
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200 if request.headers.get("user-agent") == "HomeAtlas/1.0 (+https://github.com/TorstenAmshove/HomeAtlas)" else 418,
            text=registry,
        )
    )

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(oui.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(oui, "_CACHE_PATH", tmp_path / "oui.json")
    monkeypatch.setattr(oui, "_loaded", None)

    ok, _ = asyncio.run(oui.refresh_from_ieee())

    assert ok
    assert oui.lookup("00:00:00:11:22:33") == "Vendor 0"
