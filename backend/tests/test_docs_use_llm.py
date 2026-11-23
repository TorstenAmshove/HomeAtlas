import asyncio

from app import db, llm_providers
from app.routes import docs as routes_docs


def test_use_llm_true_does_not_override_disabled_setting(temp_db, monkeypatch):
    calls = []

    async def chat(*a, **k):
        calls.append(1)
        return type("R", (), {"text": "x"})()

    monkeypatch.setattr(llm_providers, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(llm_providers, "chat", chat)
    db.create_system({"kind": "server", "name": "S", "ip": "192.168.1.5"})
    db.update_settings({"scanUseLlm": False})
    asyncio.run(routes_docs.generate_docs(body={"useLlm": True}, _={}))
    assert calls == []
