"""Persistence for chats (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _dump, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------------

def create_chat(title: str = "Neue Unterhaltung", user_id: str | None = None) -> dict:
    chat_id = _new_id()
    now = _now()
    with _conn() as conn:
        conn.execute("INSERT INTO chats(id, title, createdAt, updatedAt, userId) VALUES(?,?,?,?,?)",
                     (chat_id, title, now, now, user_id))
    return {"id": chat_id, "title": title, "createdAt": now, "updatedAt": now, "userId": user_id}


def list_chats(user_id: str | None = None) -> list[dict]:
    """All chats, or only those owned by `user_id` when given."""
    with _conn() as conn:
        if user_id is None:
            return _rows(conn.execute("SELECT * FROM chats ORDER BY updatedAt DESC"))
        return _rows(conn.execute("SELECT * FROM chats WHERE userId = ? ORDER BY updatedAt DESC", (user_id,)))


def get_chat(chat_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone())


def rename_chat(chat_id: str, title: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def delete_chat(chat_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM chatMessages WHERE chatId = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


def add_chat_message(chat_id: str, role: str, content: str = "", tool_calls: list | None = None,
                     tool_call_id: str | None = None, name: str | None = None,
                     provider_raw: dict | None = None, duration_ms: int | None = None) -> dict:
    message_id = _new_id()
    now = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO chatMessages(id, chatId, role, content, toolCalls, providerRaw, toolCallId, name, "
            "createdAt, durationMs) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (message_id, chat_id, role, content, _dump(tool_calls), _dump(provider_raw or None),
             tool_call_id, name, now, duration_ms),
        )
        conn.execute("UPDATE chats SET updatedAt = ? WHERE id = ?", (now, chat_id))
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM chatMessages WHERE id = ?", (message_id,)).fetchone())  # type: ignore[return-value]


def list_chat_messages(chat_id: str) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute("SELECT * FROM chatMessages WHERE chatId = ? ORDER BY createdAt, rowid", (chat_id,)))


def last_chat_message_rowid(chat_id: str) -> int:
    """Highest rowid of the chat's messages (0 for an empty chat); anchor for rolling back a round."""
    with _conn() as conn:
        return conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM chatMessages WHERE chatId = ?",
                            (chat_id,)).fetchone()[0]


def delete_chat_messages_after(chat_id: str, rowid: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM chatMessages WHERE chatId = ? AND rowid > ?", (chat_id, rowid))
