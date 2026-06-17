from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
from typing import Protocol

import requests

from .models import ChatMessage, MemoryItem


COMMON_TAGS = ["source:weflow", "chat:wechat"]


class MemoryBackend(Protocol):
    def write(self, items: list[MemoryItem]) -> None:
        ...


def _message_metadata(message: ChatMessage) -> dict[str, str]:
    return {
        "source": "WeFlow微信导出",
        "chat_type": "微信私聊",
        "userID": message.user_id,
        "sender_name": message.sender_name,
        "timestamp": message.timestamp,
        "local_id": str(message.local_id),
    }


def build_memory_items(messages: list[ChatMessage], *, group_by: str = "day") -> list[MemoryItem]:
    if group_by not in {"message", "day"}:
        raise ValueError("group_by must be 'message' or 'day'")
    if group_by == "message":
        return [
            MemoryItem(
                content=f"{message.timestamp} userID={message.user_id} {message.sender_name}: {message.content}",
                metadata=_message_metadata(message),
                timestamp=message.timestamp,
                participants=[message.user_id],
                tags=[*COMMON_TAGS, f"user:{message.user_id}"],
            )
            for message in messages
        ]

    grouped: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.date].append(message)
    items: list[MemoryItem] = []
    for date, day_messages in sorted(grouped.items()):
        content = "\n".join(
            f"{message.timestamp} userID={message.user_id} {message.sender_name}: {message.content}"
            for message in day_messages
        )
        participant_ids = ",".join(sorted({message.user_id for message in day_messages}))
        participants = participant_ids.split(",")
        items.append(
            MemoryItem(
                content=content,
                metadata={
                    "source": "WeFlow微信导出",
                    "chat_type": "微信私聊",
                    "date": date,
                    "userID": participant_ids,
                    "participant_user_ids": participant_ids,
                    "start_timestamp": day_messages[0].timestamp,
                    "end_timestamp": day_messages[-1].timestamp,
                    "message_count": str(len(day_messages)),
                },
                timestamp=day_messages[0].timestamp,
                participants=participants,
                tags=[*COMMON_TAGS, *(f"user:{user_id}" for user_id in participants)],
            )
        )
    return items


def write_jsonl(items: list[MemoryItem], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


class JsonlBackend:
    def __init__(self, output: Path) -> None:
        self.output = output

    def write(self, items: list[MemoryItem]) -> None:
        write_jsonl(items, self.output)


class HindsightBackend:
    def __init__(self, api_url: str, api_key: str, bank_id: str, *, verify_tls: bool = True) -> None:
        self.api_url = api_url.rstrip("/")
        self.bank_id = bank_id
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def write(self, items: list[MemoryItem]) -> None:
        payload = {
            "items": [
                {
                    "text": item.content,
                    "metadata": item.metadata,
                    "tags": item.tags,
                    "timestamp": item.timestamp,
                    "participants": item.participants,
                }
                for item in items
            ],
            "async": True,
        }
        response = self.session.post(
            f"{self.api_url}/v1/default/banks/{self.bank_id}/memories",
            json=payload,
            verify=self.verify_tls,
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Hindsight HTTP {response.status_code}: {response.text[:1000]}")


class GenericHttpBackend:
    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.url = url
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def write(self, items: list[MemoryItem]) -> None:
        response = self.session.post(
            self.url,
            json={"items": [asdict(item) for item in items]},
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"generic HTTP {response.status_code}: {response.text[:1000]}")


class Mem0Backend:
    def __init__(self, api_key: str | None = None) -> None:
        try:
            from mem0 import MemoryClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Mem0 backend requires `pip install mem0ai` or a compatible mem0 package") from exc
        self.client = MemoryClient(api_key=api_key) if api_key else MemoryClient()

    def write(self, items: list[MemoryItem]) -> None:
        for item in items:
            user_id = item.metadata.get("userID", "wechat")
            self.client.add(item.content, user_id=user_id, metadata=item.metadata)
