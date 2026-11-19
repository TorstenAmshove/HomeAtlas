"""The in-app assistant: chats and messages (tool loop in tools.py).

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .. import (db, llm_providers,
               tools)
from ..deps import (current_user)

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------------------------

@router.get("/api/chats")
async def list_chats(_: dict = Depends(current_user)) -> dict:
    return {"chats": db.list_chats()}


@router.post("/api/chats")
async def create_chat(_: dict = Depends(current_user)) -> dict:
    return {"chat": db.create_chat()}


@router.get("/api/chats/{chat_id}/messages")
async def list_messages(chat_id: str, _: dict = Depends(current_user)) -> dict:
    if db.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Unterhaltung nicht gefunden.")
    # Tool traffic is machine chatter; the UI shows which checks ran via `toolsUsed`.
    messages = [m for m in db.list_chat_messages(chat_id) if m["role"] in ("user", "assistant") and m["content"]]
    return {"messages": messages}


class ChatBody(BaseModel):
    message: str = Field(min_length=1)


@router.post("/api/chats/{chat_id}/messages")
async def send_message(chat_id: str, body: ChatBody, _: dict = Depends(current_user)) -> dict:
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Unterhaltung nicht gefunden.")
    settings = db.get_settings()
    provider = settings.get("llmProvider", "")
    # Ollama runs without a key; every cloud provider needs one, and failing here gives a usable
    # message instead of a raw 401 from the provider.
    if not llm_providers.is_configured(provider, settings):
        raise HTTPException(status_code=400, detail=(
            "Es ist noch kein KI-Zugang eingerichtet. Bitte unter Einstellungen -> KI-Assistent "
            "einen Anbieter und einen Schlüssel hinterlegen."
        ))
    if chat["title"] == "Neue Unterhaltung":
        db.rename_chat(chat_id, body.message.strip()[:60])
    try:
        return await tools.run_chat_turn(chat_id, body.message, settings)
    except llm_providers.ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Der KI-Anbieter meldet: {exc}") from exc


@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, _: dict = Depends(current_user)) -> dict:
    db.delete_chat(chat_id)
    return {"ok": True}
