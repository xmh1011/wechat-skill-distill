from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_RULES = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    ("id_card", re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"), "[ID_CARD]"),
    ("bank_card", re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)"), "[BANK_CARD]"),
    ("url", re.compile(r"https?://[^\s]+"), "[URL]"),
]


def _load_rules(policy: Path | None = None) -> list[tuple[str, re.Pattern[str], str]]:
    if not policy:
        return DEFAULT_RULES
    data = json.loads(policy.read_text(encoding="utf-8"))
    rules = []
    for item in data.get("rules", []):
        name = item["name"]
        pattern = re.compile(item["pattern"])
        replacement = item.get("replacement", f"[{name.upper()}]")
        rules.append((name, pattern, replacement))
    return rules or DEFAULT_RULES


def redact_text(text: str, *, rules: list[tuple[str, re.Pattern[str], str]] | None = None) -> tuple[str, dict[str, int]]:
    result = text
    counts: dict[str, int] = {}
    for name, pattern, replacement in rules or DEFAULT_RULES:
        result, count = pattern.subn(replacement, result)
        if count:
            counts[name] = counts.get(name, 0) + count
    return result, counts


def redact_weflow_export(data: dict[str, Any], *, policy: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    rules = _load_rules(policy)
    redacted = deepcopy(data)
    messages = redacted.get("messages") if isinstance(redacted, dict) else None
    if not isinstance(messages, list):
        raise ValueError("WeFlow export does not contain a messages list")

    total_by_rule: dict[str, int] = {}
    changed_messages: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            continue
        original = message["content"]
        masked, counts = redact_text(original, rules=rules)
        if masked == original:
            continue
        message["content"] = masked
        for name, count in counts.items():
            total_by_rule[name] = total_by_rule.get(name, 0) + count
        changed_messages.append(
            {
                "index": index,
                "local_id": message.get("localId"),
                "replacements": counts,
            }
        )

    report = {
        "summary": {
            "messages_scanned": len(messages),
            "messages_changed": len(changed_messages),
            "total_replacements": sum(total_by_rule.values()),
        },
        "replacements_by_rule": dict(sorted(total_by_rule.items())),
        "changed_messages": changed_messages,
    }
    return redacted, report


def redact_weflow_file(input_path: Path, output_path: Path, *, report_path: Path | None = None, policy: Path | None = None) -> dict[str, Any]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    redacted, report = redact_weflow_export(data, policy=policy)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
