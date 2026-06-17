from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatMessage:
    local_id: int
    timestamp: str
    date: str
    sender_name: str
    user_id: str
    message_type: str
    content: str


@dataclass(frozen=True)
class MemoryItem:
    content: str
    metadata: dict[str, str]
    tags: list[str] = field(default_factory=list)
