from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from .weflow import SKIPPED_CONTENT_PLACEHOLDERS, SUPPORTED_MESSAGE_TYPES, _clean_text, _identity, _timestamp


def _messages_from_export(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        raise ValueError(f"{path} does not contain a messages list")
    return messages


def inspect_weflow_export(path: Path, *, participants: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    participant_map = participants or {}
    raw_messages = _messages_from_export(path)
    type_counts: Counter[str] = Counter()
    skipped_by_reason: Counter[str] = Counter()
    participant_counts: dict[str, dict[str, Any]] = {}
    observed_sender_keys: set[str] = set()
    unmapped_sender_keys: set[str] = set()
    timestamps: list[str] = []
    importable_count = 0

    for raw in raw_messages:
        if not isinstance(raw, dict):
            skipped_by_reason["invalid_record"] += 1
            continue

        message_type = str(raw.get("type") or "unknown")
        type_counts[message_type] += 1

        sender_username = str(raw.get("senderUsername") or "")
        is_send = str(raw.get("isSend", ""))
        if sender_username:
            observed_sender_keys.add(sender_username)
        if is_send:
            observed_sender_keys.add(is_send)

        if message_type not in SUPPORTED_MESSAGE_TYPES:
            skipped_by_reason["unsupported_type"] += 1
            continue

        content = _clean_text(str(raw.get("content") or ""))
        if not content:
            skipped_by_reason["empty_content"] += 1
            continue
        if content in SKIPPED_CONTENT_PLACEHOLDERS:
            skipped_by_reason["placeholder_content"] += 1
            continue

        try:
            timestamp = _timestamp(raw)
        except Exception:
            skipped_by_reason["invalid_timestamp"] += 1
            continue

        identity_keys = [key for key in [sender_username, is_send] if key]
        if participant_map and not any(key in participant_map for key in identity_keys):
            unmapped_sender_keys.add(sender_username or is_send or "unknown")
        user_id, sender_name = _identity(raw, participant_map)
        entry = participant_counts.setdefault(
            user_id,
            {
                "user_id": user_id,
                "name": sender_name,
                "message_count": 0,
                "message_types": defaultdict(int),
            },
        )
        entry["message_count"] += 1
        entry["message_types"][message_type] += 1
        timestamps.append(timestamp)
        importable_count += 1

    participants_report = []
    for entry in participant_counts.values():
        participants_report.append(
            {
                "user_id": entry["user_id"],
                "name": entry["name"],
                "message_count": entry["message_count"],
                "message_types": dict(sorted(entry["message_types"].items())),
            }
        )
    participants_report.sort(key=lambda item: (-item["message_count"], item["user_id"]))

    configured_keys = set(participant_map)
    return {
        "input": str(path),
        "raw_messages": len(raw_messages),
        "importable_messages": importable_count,
        "skipped_messages": sum(skipped_by_reason.values()),
        "date_range": {
            "start": min(timestamps) if timestamps else None,
            "end": max(timestamps) if timestamps else None,
        },
        "participants": participants_report,
        "message_types": dict(sorted(type_counts.items())),
        "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
        "configured_participant_keys": sorted(configured_keys),
        "observed_sender_keys": sorted(observed_sender_keys),
        "unmapped_sender_keys": sorted(unmapped_sender_keys),
    }
