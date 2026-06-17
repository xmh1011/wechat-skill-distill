from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from .models import ChatMessage


REQUIRED_SECTIONS = [
    "目标",
    "使用时机",
    "说话风格画像",
    "场景模板",
    "真实样本",
    "生成规则",
    "硬边界",
    "自检",
]
MEMORY_TERMS = ["## 记忆检索", "HINDSIGHT_API_KEY", "MEM0_API_KEY", "MEMORY_API_KEY", "Hindsight", "Mem0"]


@dataclass
class SkillEvaluation:
    path: str
    user_id: str | None
    name: str
    kind: str
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "user_id": self.user_id,
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "issues": self.issues,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def collect_skill_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(path)
    found = [*path.glob("*.skill"), *path.glob("*.chat-memory.skill")]
    return sorted(set(found))


def _skill_name(text: str, path: Path) -> str:
    match = re.search(r"^#\s+(.+?)\s+(?:Chat\s+)?Skill\s*$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return path.name.split(".")[0]


def _skill_user_id(text: str) -> str | None:
    match = re.search(r"userID=([^\s，。`]+)", text)
    return match.group(1) if match else None


def _section_text(text: str, section: str) -> str:
    pattern = rf"^## {re.escape(section)}\s*$([\s\S]*?)(?=^## |\Z)"
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _messages_by_user(messages: list[ChatMessage] | None) -> dict[str, list[ChatMessage]]:
    by_user: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages or []:
        by_user[message.user_id].append(message)
    return dict(by_user)


def evaluate_skill_file(path: Path, *, messages: list[ChatMessage] | None = None) -> SkillEvaluation:
    text = path.read_text(encoding="utf-8")
    name = _skill_name(text, path)
    user_id = _skill_user_id(text)
    memory_aware = "## 记忆检索" in text or path.name.endswith(".chat-memory.skill")
    kind = "chat-memory" if memory_aware else "style"
    result = SkillEvaluation(path=str(path), user_id=user_id, name=name, kind=kind)

    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text:
            result.issues.append(f"missing section: {section}")

    if kind == "style":
        found_terms = [term for term in MEMORY_TERMS if term in text]
        if found_terms:
            result.issues.append(f"style skill contains memory terms: {', '.join(found_terms)}")
    else:
        if "## 记忆检索" not in text:
            result.issues.append("chat-memory skill missing memory recall section")

    if not user_id:
        result.issues.append("missing userID marker")

    by_user = _messages_by_user(messages)
    other_names = sorted({m.sender_name for uid, rows in by_user.items() if uid != user_id for m in rows})
    own_messages = by_user.get(user_id or "", [])
    other_name_hits = [other for other in other_names if other and other in text]
    if other_name_hits:
        result.issues.append(f"contains other participant names: {', '.join(other_name_hits)}")

    sample_section = _section_text(text, "真实样本")
    outside_samples_text = text.replace(sample_section, "")
    leaked_outside_samples = []
    for message in own_messages:
        content = message.content.strip()
        if len(content) >= 8 and content in outside_samples_text:
            leaked_outside_samples.append(content)
    if leaked_outside_samples:
        result.warnings.append(f"verbatim source text outside sample section: {len(leaked_outside_samples)}")

    sample_count = len(re.findall(r"```text\n[\s\S]*?\n```", sample_section))
    result.metrics = {
        "character_count": len(text),
        "required_sections_present": sum(1 for section in REQUIRED_SECTIONS if f"## {section}" in text),
        "sample_count": sample_count,
        "other_name_hits": other_name_hits,
    }
    if sample_count == 0:
        result.warnings.append("no fenced text samples found")
    return result


def evaluate_skills(paths: list[Path], *, messages: list[ChatMessage] | None = None) -> dict[str, Any]:
    evaluations = [evaluate_skill_file(path, messages=messages).as_dict() for path in paths]
    return {
        "summary": {
            "files": len(evaluations),
            "passed": sum(1 for item in evaluations if item["passed"]),
            "failed": sum(1 for item in evaluations if not item["passed"]),
            "warnings": sum(len(item["warnings"]) for item in evaluations),
        },
        "skills": evaluations,
    }
