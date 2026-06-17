from __future__ import annotations

from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class SkillMeta:
    name: str
    user_id: str | None
    memory_aware: bool
    phrases: list[str]
    sample_count: int


def frontmatter_block(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    body = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(body)
        body.append(line)
    return ""


def frontmatter_value(text: str, key: str) -> str | None:
    block = frontmatter_block(text)
    if not block:
        return None
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", block, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    if value.startswith(('"', "'")):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value.strip("\"'")
    return value


def skill_title_name(text: str, fallback: str = "") -> str:
    match = re.search(r"^#\s+(.+?)\s+(?:Chat\s+)?Skill\s*$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def skill_user_id(text: str) -> str | None:
    frontmatter_user_id = frontmatter_value(text, "user_id")
    if frontmatter_user_id:
        return frontmatter_user_id
    match = re.search(r"userID=([^\s，。`]+)", text)
    return match.group(1) if match else None


def skill_phrases(text: str) -> list[str]:
    match = re.search(r"常见表达：([^\n]+)", text)
    if not match:
        return []
    line = re.sub(r"[。.;；]\s*$", "", match.group(1))
    return [item.strip() for item in re.split(r"[、,，]", line) if item.strip()][:16]


def skill_sample_count(text: str) -> int:
    return len(re.findall(r"```text\n[\s\S]*?\n```", text))


def parse_skill_meta(text: str, *, fallback_name: str = "") -> SkillMeta:
    return SkillMeta(
        name=frontmatter_value(text, "display_name") or skill_title_name(text, fallback_name) or fallback_name,
        user_id=skill_user_id(text),
        memory_aware="## 记忆检索" in text,
        phrases=skill_phrases(text),
        sample_count=skill_sample_count(text),
    )
