"""Conversation history store for the RAG Q&A feature.

Each workspace keeps its own history file under ``.agni/chat_history.json``.
Every conversation holds its message content, last-updated time and a title,
matching the workspace-scoped JSON store pattern used by the other UI models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CHAT_HISTORY_STORE_RELATIVE_PATH = Path(".agni") / "chat_history.json"

CONVERSATION_ID_KEY = "id"
CONVERSATION_TITLE_KEY = "title"
CONVERSATION_PINNED_KEY = "pinned"
CONVERSATION_CREATED_KEY = "created_at"
CONVERSATION_UPDATED_KEY = "updated_at"
CONVERSATION_MESSAGES_KEY = "messages"


def chat_history_path(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / CHAT_HISTORY_STORE_RELATIVE_PATH


def load_conversations(workspace_root: Path | str | None) -> list[dict[str, Any]]:
    """Load all conversations for the given workspace root."""
    if workspace_root is None:
        return []

    store_path = chat_history_path(workspace_root)
    if not store_path.exists():
        return []

    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_conversations = data.get("conversations", []) if isinstance(data, dict) else []
    if not isinstance(raw_conversations, list):
        return []

    conversations: list[dict[str, Any]] = []
    for record in raw_conversations:
        if not isinstance(record, dict):
            continue
        conversation_id = str(record.get("id") or "").strip()
        if not conversation_id:
            continue

        messages: list[dict[str, str]] = []
        raw_messages = record.get("messages", [])
        if isinstance(raw_messages, list):
            for message in raw_messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "")
                if role not in {"user", "assistant"}:
                    continue
                messages.append({"role": role, "content": str(message.get("content") or "")})

        conversations.append({
            CONVERSATION_ID_KEY: conversation_id,
            CONVERSATION_TITLE_KEY: str(record.get("title") or "未命名对话"),
            CONVERSATION_PINNED_KEY: bool(record.get("pinned")),
            CONVERSATION_CREATED_KEY: str(record.get("created_at") or ""),
            CONVERSATION_UPDATED_KEY: str(record.get("updated_at") or ""),
            CONVERSATION_MESSAGES_KEY: messages,
        })
    return conversations


def save_conversations(
    workspace_root: Path | str,
    conversations: list[dict[str, Any]],
) -> None:
    """Persist conversations for the given workspace root."""
    store_path = chat_history_path(workspace_root)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
