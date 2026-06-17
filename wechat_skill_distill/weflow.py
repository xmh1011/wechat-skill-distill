from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .models import ChatMessage


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
def _clean_text(content: str) -> str:
    text = content.strip()
    if "[引用 " in text:
        text = text.split("[引用 ", 1)[0].strip()
    return re.sub(r"\s+", " ", text).strip()


def _timestamp(message: dict[str, Any]) -> str:
    formatted = message.get("formattedTime")
    if formatted:
        return datetime.strptime(str(formatted), "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ).isoformat()
    create_time = int(message["createTime"])
    return datetime.fromtimestamp(create_time, LOCAL_TZ).isoformat()


def _identity(message: dict[str, Any], participants: dict[str, dict[str, str]]) -> tuple[str, str]:
    sender_username = str(message.get("senderUsername") or "")
    is_send = str(message.get("isSend", ""))
    for key in [sender_username, is_send]:
        if key and key in participants:
            configured = participants[key]
            return configured["user_id"], configured["name"]
    display_name = str(message.get("senderDisplayName") or "")
    user_id = sender_username or f"participant_{is_send or 'unknown'}"
    return user_id, display_name or user_id


def load_weflow_messages(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    participants: dict[str, dict[str, str]] | None = None,
) -> list[ChatMessage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        raise ValueError(f"{path} does not contain a messages list")
    participant_map = participants or {}
    result: list[ChatMessage] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        message_type = str(raw.get("type") or "")
        if message_type not in {"文本消息", "引用消息"}:
            continue
        content = _clean_text(str(raw.get("content") or ""))
        if not content or content in {"[图片]", "[动画表情]", "[语音]", "[视频]"}:
            continue
        timestamp = _timestamp(raw)
        date = timestamp[:10]
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        user_id, sender_name = _identity(raw, participant_map)
        result.append(
            ChatMessage(
                local_id=int(raw.get("localId") or 0),
                timestamp=timestamp,
                date=date,
                sender_name=sender_name,
                user_id=user_id,
                message_type=message_type,
                content=content,
            )
        )
    return result
