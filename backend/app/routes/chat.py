"""The in-app assistant: chats and messages (tool loop in tools.py).

Chats belong to the user who started them (#49): everyone sees, reads, continues and deletes only
their own; ADMIN sees all. Chats from before ownership existed have no owner and are admin-only.
A chat someone may not see answers 404, not 403, so its existence is not revealed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db, llm_providers, tools
from ..deps import current_user

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------------------------

def _is_admin(user: dict) -> bool:
    return user.get("role") == auth.ROLE_ADMIN


def _visible_chat(chat_id: str, user: dict) -> dict:
    chat = db.get_chat(chat_id)
    if chat is None or not (_is_admin(user) or (chat.get("userId") and chat["userId"] == user.get("id"))):
        raise HTTPException(status_code=404, detail="Unterhaltung nicht gefunden.")
    return chat


@router.get("/api/chats")
async def list_chats(user: dict = Depends(current_user)) -> dict:
    return {"chats": db.list_chats(None if _is_admin(user) else user["id"])}


@router.post("/api/chats")
async def create_chat(user: dict = Depends(current_user)) -> dict:
    return {"chat": db.create_chat(user_id=user["id"])}


@router.get("/api/chats/{chat_id}/messages")
async def list_messages(chat_id: str, user: dict = Depends(current_user)) -> dict:
    _visible_chat(chat_id, user)
    # Tool traffic is machine chatter; the UI shows which checks ran via `toolsUsed`.
    messages = [m for m in db.list_chat_messages(chat_id) if m["role"] in ("user", "assistant") and m["content"]]
    return {"messages": messages}


class ChatBody(BaseModel):
    message: str = Field(min_length=1)


@router.post("/api/chats/{chat_id}/messages")
async def send_message(chat_id: str, body: ChatBody, user: dict = Depends(current_user)) -> dict:
    chat = _visible_chat(chat_id, user)
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
        return await tools.run_chat_turn(chat_id, body.message, settings, user=user)
    except llm_providers.ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Der KI-Anbieter meldet: {exc}") from exc


@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, user: dict = Depends(current_user)) -> dict:
    _visible_chat(chat_id, user)
    db.delete_chat(chat_id)
    return {"ok": True}
