from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .memory import (
    GenericHttpBackend,
    HindsightBackend,
    JsonlBackend,
    Mem0Backend,
    build_memory_items,
)
from .skills import generate_skill_texts, write_skill_files
from .weflow import load_weflow_messages


def load_config(path: Path | None) -> dict:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_participants(path: Path | None, config: dict | None = None) -> dict[str, dict[str, str]]:
    if path:
        return json.loads(path.read_text(encoding="utf-8"))
    if config and isinstance(config.get("participants"), dict):
        return config["participants"]
    return {}


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    config = load_config(args.config)
    participants = load_participants(args.participants, config)
    if args.input:
        path = Path(args.input)
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            ok = False
        else:
            messages = load_weflow_messages(path, participants=participants)
            users = sorted({message.user_id for message in messages})
            print(f"input ok: {path} ({len(messages)} messages, users={','.join(users)})")
    for name in ["HINDSIGHT_API_URL", "HINDSIGHT_API_KEY", "MEM0_API_KEY", "MEMORY_API_KEY"]:
        print(f"{name}: {'set' if os.getenv(name) else 'unset'}")
    return 0 if ok else 1


def cmd_weflow_guide(_: argparse.Namespace) -> int:
    print(
        """WeFlow 导出建议：
1. 在 WeFlow 中选择目标微信私聊。
2. 导出 JSON，保留 messages、formattedTime、isSend、senderDisplayName 字段。
3. 将 JSON 放在仓库外或 data/ 下，避免提交原始聊天记录。
4. 先运行：wechat-skill-distill doctor --input <export.json>
"""
    )
    return 0


def _messages_from_args(args: argparse.Namespace):
    config = load_config(args.config)
    participants = load_participants(args.participants, config)
    return load_weflow_messages(args.input, start_date=args.start_date, end_date=args.end_date, participants=participants)


def cmd_extract_skills(args: argparse.Namespace) -> int:
    messages = _messages_from_args(args)
    skills = generate_skill_texts(messages, include_memory=False)
    written = write_skill_files(skills, args.out_dir, suffix="skill")
    for path in written:
        print(path)
    return 0


def cmd_generate_chat_skills(args: argparse.Namespace) -> int:
    messages = _messages_from_args(args)
    skills = generate_skill_texts(messages, include_memory=True, memory_backend=args.memory_backend)
    written = write_skill_files(skills, args.out_dir, suffix="chat-memory.skill")
    for path in written:
        print(path)
    return 0


def _backend_from_args(args: argparse.Namespace, config: dict):
    backend = args.backend
    if backend == "jsonl":
        output = args.output or Path(config.get("jsonl_output", "exports/memory.jsonl"))
        return JsonlBackend(output)
    if backend == "hindsight":
        api_key = args.api_key or os.getenv("HINDSIGHT_API_KEY") or config.get("hindsight_api_key")
        if not api_key:
            raise RuntimeError("hindsight backend requires HINDSIGHT_API_KEY or --api-key")
        api_url = args.api_url or os.getenv("HINDSIGHT_API_URL") or config.get("hindsight_api_url")
        if not api_url:
            raise RuntimeError("hindsight backend requires HINDSIGHT_API_URL or --api-url")
        return HindsightBackend(
            api_url,
            api_key,
            args.bank_id or os.getenv("HINDSIGHT_BANK_ID") or config.get("hindsight_bank_id", "default-bank"),
            verify_tls=not args.insecure,
        )
    if backend == "mem0":
        return Mem0Backend(args.api_key or os.getenv("MEM0_API_KEY") or config.get("mem0_api_key"))
    if backend == "generic-http":
        url = args.api_url or config.get("generic_http_url") or os.getenv("MEMORY_WRITE_URL")
        if not url:
            raise RuntimeError("generic-http backend requires --api-url or MEMORY_WRITE_URL")
        return GenericHttpBackend(url, args.api_key or os.getenv("MEMORY_API_KEY") or config.get("memory_api_key"))
    raise RuntimeError(f"unsupported backend: {backend}")


def cmd_import(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    participants = load_participants(args.participants, config)
    messages = load_weflow_messages(args.input, start_date=args.start_date, end_date=args.end_date, participants=participants)
    items = build_memory_items(messages, group_by=args.group_by)
    if args.dry_run:
        output = args.output or Path("exports/memory.dry-run.jsonl")
        JsonlBackend(output).write(items)
        print(f"dry-run wrote {len(items)} items to {output}")
        return 0
    backend = _backend_from_args(args, config)
    backend.write(items)
    print(f"wrote {len(items)} items to {args.backend}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wechat-skill-distill")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check local config and input file")
    doctor.add_argument("--input", type=Path)
    doctor.add_argument("--config", type=Path)
    doctor.add_argument("--participants", type=Path)
    doctor.set_defaults(func=cmd_doctor)

    guide = sub.add_parser("weflow-guide", help="print WeFlow export guidance")
    guide.set_defaults(func=cmd_weflow_guide)

    extract = sub.add_parser("extract-skills", help="generate per-user chat skills from a WeFlow JSON")
    extract.add_argument("--input", required=True, type=Path)
    extract.add_argument("--out-dir", required=True, type=Path)
    extract.add_argument("--memory-backend", choices=["hindsight", "mem0", "jsonl", "generic-http"], help=argparse.SUPPRESS)
    extract.add_argument("--config", type=Path)
    extract.add_argument("--participants", type=Path)
    extract.add_argument("--start-date")
    extract.add_argument("--end-date")
    extract.set_defaults(func=cmd_extract_skills)

    chat_skills = sub.add_parser("generate-chat-skills", help="generate per-user chat skills with memory recall instructions")
    chat_skills.add_argument("--input", required=True, type=Path)
    chat_skills.add_argument("--out-dir", required=True, type=Path)
    chat_skills.add_argument("--memory-backend", default="jsonl", choices=["hindsight", "mem0", "jsonl", "generic-http"])
    chat_skills.add_argument("--config", type=Path)
    chat_skills.add_argument("--participants", type=Path)
    chat_skills.add_argument("--start-date")
    chat_skills.add_argument("--end-date")
    chat_skills.set_defaults(func=cmd_generate_chat_skills)

    imp = sub.add_parser("import", help="import chat messages into a memory backend")
    imp.add_argument("--input", required=True, type=Path)
    imp.add_argument("--backend", required=True, choices=["hindsight", "mem0", "jsonl", "generic-http"])
    imp.add_argument("--group-by", default="day", choices=["day", "message"])
    imp.add_argument("--config", type=Path)
    imp.add_argument("--participants", type=Path)
    imp.add_argument("--output", type=Path)
    imp.add_argument("--api-url")
    imp.add_argument("--api-key")
    imp.add_argument("--bank-id")
    imp.add_argument("--start-date")
    imp.add_argument("--end-date")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--insecure", action="store_true")
    imp.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
