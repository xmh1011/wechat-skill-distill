#!/usr/bin/env python3
"""Import a WeFlow WeChat JSON export into a Hindsight memory bank."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


API_URL_DEFAULT = "https://cloud.memory.bj.baidubce.com/api"
BANK_ID_DEFAULT = "wechat-memory"
CONVERSATION_ID = "wechat-661-662"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

USER_BY_DISPLAY_NAME = {
    "胡翔川": {"user_id": "661", "canonical_name": "Hu Xiangchuan", "display_name": "胡翔川"},
    "牧之": {"user_id": "662", "canonical_name": "Xiao Minghao", "display_name": "牧之"},
}

ENTITIES = [
    {"text": "胡翔川", "type": "PERSON"},
    {"text": "Hu Xiangchuan", "type": "PERSON"},
    {"text": "661", "type": "PERSON"},
    {"text": "肖明浩", "type": "PERSON"},
    {"text": "Xiao Minghao", "type": "PERSON"},
    {"text": "牧之", "type": "PERSON"},
    {"text": "662", "type": "PERSON"},
]

COMMON_TAGS = [
    "source:weflow",
    "chat:wechat",
    f"conversation:{CONVERSATION_ID}",
    "user:661",
    "user:662",
]

OBSERVATION_SCOPES = [
    ["user:661"],
    ["user:662"],
    [f"conversation:{CONVERSATION_ID}"],
    ["user:661", "user:662"],
]


@dataclass(frozen=True)
class ChatMessage:
    local_id: int
    timestamp: str
    date: str
    sender_name: str
    user_id: str
    message_type: str
    content: str


class HindsightClient:
    def __init__(self, api_url: str, api_key: str, bank_id: str, verify_tls: bool) -> None:
        self.api_url = api_url.rstrip("/")
        self.bank_id = bank_id
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        if not verify_tls:
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.api_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=120,
                    verify=self.verify_tls,
                    **kwargs,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:2000]}")
                if not response.text:
                    return {}
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(2**attempt)
        raise RuntimeError(f"request failed: {last_error}") from last_error

    def stats(self) -> dict[str, Any]:
        return self.request("GET", f"/v1/default/banks/{self.bank_id}/stats")

    def configure_bank(self) -> dict[str, Any]:
        retain_mission = (
            "Extract durable facts and patterns from the WeChat conversation between user 661 "
            "(Hu Xiangchuan) and user 662 (Xiao Minghao). Preserve who said what, when it was "
            "said, stable preferences, work context, emotional patterns, relationship dynamics, "
            "recurring habits, plans, health/status updates, and communication style. Ignore pure "
            "greetings, filler laughter, one-off jokes with no durable meaning, and duplicate "
            "small talk unless it establishes a recurring pattern."
        )
        observations_mission = (
            "Create evidence-grounded observations about user 661, user 662, and their shared "
            "conversation context. Focus on stable preferences, communication style, recurring "
            "topics, relationship dynamics, work/stress patterns, and changes over time. Do not "
            "over-infer romantic intent from isolated playful messages; mark uncertainty when "
            "evidence is mixed."
        )
        payload = {
            "updates": {
                "retain_mission": retain_mission,
                "observations_mission": observations_mission,
                "retain_extraction_mode": "verbose",
                "enable_observations": True,
            }
        }
        return self.request("PATCH", f"/v1/default/banks/{self.bank_id}/config", json=payload)

    def retain(self, items: list[dict[str, Any]], retain_async: bool) -> dict[str, Any]:
        payload = {"items": items, "async": retain_async}
        return self.request("POST", f"/v1/default/banks/{self.bank_id}/memories", json=payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to WeFlow JSON export")
    parser.add_argument("--api-url", default=os.getenv("HINDSIGHT_API_URL", API_URL_DEFAULT))
    parser.add_argument("--bank-id", default=os.getenv("HINDSIGHT_BANK_ID", BANK_ID_DEFAULT))
    parser.add_argument("--api-key", default=os.getenv("HINDSIGHT_API_KEY"))
    parser.add_argument("--group-by", choices=["day", "message"], default="day")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="Limit retained items after grouping")
    parser.add_argument("--start-date", help="Inclusive YYYY-MM-DD filter")
    parser.add_argument("--end-date", help="Inclusive YYYY-MM-DD filter")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true", help="Only print bank stats and operation status")
    parser.add_argument("--sync", action="store_true", help="Wait for retain processing")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    parser.add_argument("--configure-bank", action="store_true")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    return parser.parse_args()


def own_text(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    if "[引用 " in content:
        content = content.split("[引用 ", 1)[0].strip()
    return re.sub(r"\s+", " ", content).strip()


def iso_timestamp(message: dict[str, Any]) -> str:
    formatted = message.get("formattedTime")
    if formatted:
        return datetime.strptime(formatted, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ).isoformat()
    create_time = int(message["createTime"])
    return datetime.fromtimestamp(create_time, LOCAL_TZ).isoformat()


def load_messages(path: Path, start_date: str | None, end_date: str | None) -> list[ChatMessage]:
    data = json.loads(path.read_text())
    result: list[ChatMessage] = []
    for message in data.get("messages", []):
        message_type = message.get("type")
        if message_type not in {"文本消息", "引用消息"}:
            continue
        text = own_text(message)
        if not text or text in {"[图片]", "[动画表情]", "[语音]", "[视频]"}:
            continue
        sender_name = message.get("senderDisplayName") or ""
        sender = USER_BY_DISPLAY_NAME.get(sender_name)
        if not sender:
            continue
        ts = iso_timestamp(message)
        date = ts[:10]
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        result.append(
            ChatMessage(
                local_id=int(message.get("localId") or 0),
                timestamp=ts,
                date=date,
                sender_name=sender_name,
                user_id=sender["user_id"],
                message_type=message_type,
                content=text,
            )
        )
    return result


def format_line(message: ChatMessage) -> str:
    return (
        f"{message.timestamp} userID={message.user_id} "
        f"name={message.sender_name} type={message.message_type}: {message.content}"
    )


def common_metadata() -> dict[str, str]:
    return {
        "source": "weflow",
        "chat_type": "private_wechat_chat",
        "conversation_id": CONVERSATION_ID,
        "userID": "661,662",
        "participant_user_ids": "661,662",
        "participants": "661=Hu Xiangchuan;662=Xiao Minghao",
    }


def make_day_items(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.date].append(message)

    items: list[dict[str, Any]] = []
    for date in sorted(grouped):
        day_messages = grouped[date]
        start_ts = day_messages[0].timestamp
        end_ts = day_messages[-1].timestamp
        content = "\n".join(format_line(message) for message in day_messages)
        metadata = {
            **common_metadata(),
            "grouping": "day",
            "date": date,
            "message_start_timestamp": start_ts,
            "message_end_timestamp": end_ts,
            "message_count": str(len(day_messages)),
        }
        items.append(
            {
                "content": content,
                "context": (
                    "WeFlow private WeChat chat transcript for one local day. Each line includes "
                    "the original message timestamp, userID, display name, message type, and text."
                ),
                "timestamp": end_ts,
                "metadata": metadata,
                "document_id": f"{CONVERSATION_ID}-{date}",
                "tags": COMMON_TAGS + [f"date:{date}"],
                "entities": ENTITIES,
                "observation_scopes": OBSERVATION_SCOPES,
                "update_mode": "replace",
            }
        )
    return items


def make_message_items(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        metadata = {
            **common_metadata(),
            "grouping": "message",
            "message_timestamp": message.timestamp,
            "message_local_id": str(message.local_id),
            "speaker_userID": message.user_id,
            "speaker_name": message.sender_name,
            "message_type": message.message_type,
        }
        items.append(
            {
                "content": format_line(message),
                "context": "Single WeFlow private WeChat message with timestamp and speaker userID.",
                "timestamp": message.timestamp,
                "metadata": metadata,
                "document_id": f"{CONVERSATION_ID}-msg-{message.local_id}",
                "tags": COMMON_TAGS + [f"user:{message.user_id}", f"date:{message.date}"],
                "entities": ENTITIES,
                "observation_scopes": OBSERVATION_SCOPES,
                "update_mode": "replace",
            }
        )
    return items


def batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    args = parse_args()
    if not args.dry_run and not args.api_key:
        print("HINDSIGHT_API_KEY is required unless --dry-run is used", file=sys.stderr)
        return 2

    if args.status:
        client = HindsightClient(
            api_url=args.api_url,
            api_key=args.api_key,
            bank_id=args.bank_id,
            verify_tls=not args.insecure,
        )
        stats = client.stats()
        operations = client.request("GET", f"/v1/default/banks/{args.bank_id}/operations?limit=100")
        status_counts: dict[str, int] = {}
        for operation in operations.get("operations", []):
            status = operation.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        print(
            json.dumps(
                {
                    "stats": stats,
                    "operation_total": operations.get("total"),
                    "visible_operation_status_counts": status_counts,
                    "failed_operations": [
                        operation
                        for operation in operations.get("operations", [])
                        if operation.get("status") == "failed"
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    messages = load_messages(args.input, args.start_date, args.end_date)
    items = make_day_items(messages) if args.group_by == "day" else make_message_items(messages)
    if args.limit:
        items = items[: args.limit]

    summary = {
        "input": str(args.input),
        "group_by": args.group_by,
        "messages": len(messages),
        "items": len(items),
        "first_timestamp": messages[0].timestamp if messages else None,
        "last_timestamp": messages[-1].timestamp if messages else None,
        "sample_item": items[0] if items else None,
    }
    write_json(args.logs_dir / "dry_run_summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "sample_item"}, ensure_ascii=False, indent=2))

    if args.dry_run:
        print(f"wrote {args.logs_dir / 'dry_run_summary.json'}")
        return 0

    client = HindsightClient(
        api_url=args.api_url,
        api_key=args.api_key,
        bank_id=args.bank_id,
        verify_tls=not args.insecure,
    )

    run_log: dict[str, Any] = {
        "bank_id": args.bank_id,
        "api_url": args.api_url,
        "group_by": args.group_by,
        "items": len(items),
        "batches": [],
    }
    run_log["stats_before"] = client.stats()

    if args.configure_bank:
        run_log["config_result"] = client.configure_bank()

    retain_async = not args.sync
    for index, batch in enumerate(batched(items, args.batch_size), start=1):
        response = client.retain(batch, retain_async=retain_async)
        batch_log = {
            "batch": index,
            "items_count": len(batch),
            "document_ids": [item["document_id"] for item in batch],
            "response": response,
        }
        run_log["batches"].append(batch_log)
        print(json.dumps(batch_log, ensure_ascii=False))

    run_log["stats_after_submit"] = client.stats()
    write_json(args.logs_dir / "import_run.json", run_log)
    print(f"wrote {args.logs_dir / 'import_run.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
