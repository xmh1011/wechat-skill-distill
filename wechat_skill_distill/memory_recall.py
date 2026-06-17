from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

import requests


DEFAULT_BANK_ID = "default-bank"
SMALL_TALK_MESSAGES = {
    "你好",
    "您好",
    "hi",
    "hello",
    "hey",
    "在吗",
    "早",
    "早上好",
    "晚上好",
    "晚安",
    "好",
    "嗯",
    "哦",
    "谢谢",
    "哈哈",
}


class MemoryRecallError(RuntimeError):
    pass


def _env(env: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return default


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _compact_message(value: str) -> str:
    return re.sub(r"[\s，。！？!?、,.~…]+", "", value).lower()


def memory_runtime_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    current_env = env or os.environ
    backend = _env(current_env, "WSD_MEMORY_RECALL_BACKEND", "MEMORY_RECALL_BACKEND", default="")
    api_key = _env(current_env, "WSD_HINDSIGHT_API_KEY", "HINDSIGHT_API_KEY")
    api_url = _env(current_env, "WSD_HINDSIGHT_API_URL", "HINDSIGHT_API_URL", default="https://cloud.memory.bj.baidubce.com/api")
    bank_id = _env(current_env, "WSD_HINDSIGHT_BANK_ID", "HINDSIGHT_BANK_ID", default=DEFAULT_BANK_ID)
    if not backend:
        backend = "hindsight" if api_key else "off"
    return {
        "backend": backend,
        "configured": backend == "hindsight" and bool(api_key and api_url and bank_id),
        "bank_id": bank_id if backend == "hindsight" else "",
    }


def recall_for_chat(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    current_env = env or os.environ
    status = memory_runtime_status(current_env)
    if status["backend"] in {"", "off", "none", "disabled"}:
        return []
    if status["backend"] != "hindsight":
        raise MemoryRecallError(f"unsupported memory recall backend: {status['backend']}")
    if not status["configured"]:
        return []
    return _hindsight_recall_for_chat(payload, current_env)


def _hindsight_recall_for_chat(payload: Mapping[str, Any], env: Mapping[str, str]) -> list[dict[str, Any]]:
    message = str(payload.get("message") or "").strip()
    if not message:
        return []
    if not _should_recall(message, env):
        return []
    persona = payload.get("persona") or {}
    persona_name = str(persona.get("name") or "当前人物")
    user_id = str(persona.get("userId") or "").strip()
    skill = str(payload.get("skill") or "")
    api_url = _env(env, "WSD_HINDSIGHT_API_URL", "HINDSIGHT_API_URL", default="https://cloud.memory.bj.baidubce.com/api").rstrip("/")
    api_key = _env(env, "WSD_HINDSIGHT_API_KEY", "HINDSIGHT_API_KEY")
    bank_id = _env(env, "WSD_HINDSIGHT_BANK_ID", "HINDSIGHT_BANK_ID") or _extract_bank_id(skill) or DEFAULT_BANK_ID
    tag_attempts = _recall_tag_attempts(skill, user_id, env)
    if not tag_attempts:
        tag_attempts = [([], "any_strict")]
    results: list[dict[str, Any]] = []
    history = _recent_context(payload)
    for tags, tags_match in tag_attempts:
        request_body = _recall_payload(message, persona_name, user_id, history, tags, tags_match, env)
        results = _post_hindsight_recall(api_url, api_key, bank_id, request_body, env)
        if results:
            break
    if not results and _env(env, "WSD_HINDSIGHT_DISABLE_TAG_FALLBACK", default="0") != "1":
        fallback_body = _recall_payload(message, persona_name, user_id, history, [], "any_strict", env)
        results = _post_hindsight_recall(api_url, api_key, bank_id, fallback_body, env)
    return results


def _should_recall(message: str, env: Mapping[str, str]) -> bool:
    mode = _env(env, "WSD_HINDSIGHT_RECALL_MODE", "HINDSIGHT_RECALL_MODE", default="auto").lower()
    if mode in {"off", "none", "disabled"}:
        return False
    if mode in {"always", "all"}:
        return True
    return _compact_message(message) not in SMALL_TALK_MESSAGES


def _extract_bank_id(skill: str) -> str:
    match = re.search(r"Bank[：:]\s*`?([A-Za-z0-9_.-]+)`?", skill)
    return match.group(1) if match else ""


def _extract_skill_tags(skill: str) -> list[str]:
    match = re.search(r"`?tags`?[：:]\s*`?(\[[^\n`]+\])`?", skill)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _recall_tag_attempts(skill: str, user_id: str, env: Mapping[str, str]) -> list[tuple[list[str], str]]:
    configured = _csv(_env(env, "WSD_HINDSIGHT_TAGS", "HINDSIGHT_TAGS"))
    configured_match = _env(env, "WSD_HINDSIGHT_TAGS_MATCH", "HINDSIGHT_TAGS_MATCH", default="all_strict")
    if configured:
        return [(sorted(set(configured)), configured_match)]
    attempts: list[tuple[list[str], str]] = []
    if user_id:
        attempts.append(([f"user:{user_id}"], "all_strict"))
    skill_tags = sorted(set(_extract_skill_tags(skill)))
    if skill_tags:
        attempts.append((skill_tags, "any_strict"))
    return attempts


def _recent_context(payload: Mapping[str, Any]) -> str:
    history = payload.get("history")
    if not isinstance(history, list):
        return "无"
    lines = []
    for item in history[-6:]:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip()
        text = str(item.get("text") or item.get("content") or "").strip()
        if role and text:
            lines.append(f"{role}: {text[:160]}")
    return "\n".join(lines) or "无"


def _format_query_template(template: str, values: Mapping[str, str]) -> str:
    return template.format_map({key: values.get(key, "") for key in ("name", "user_id", "message", "history")})


def _recall_payload(message: str, persona_name: str, user_id: str, history: str, tags: list[str], tags_match: str, env: Mapping[str, str]) -> dict[str, Any]:
    query_template = _env(
        env,
        "WSD_HINDSIGHT_QUERY_TEMPLATE",
        "HINDSIGHT_QUERY_TEMPLATE",
        default=(
            "检索目标人物：{name}（userID={user_id}）。\n"
            "当前用户原话：{message}\n"
            "最近对话上下文：\n{history}\n"
            "检索任务：只寻找能够直接回答当前原话的已记录事实、事件、偏好、关系或时间线证据。"
            "优先返回目标人物本人相关事实；如果问题问双方互动，才返回双方共同事实。"
            "忽略仅同属该人物但与当前原话无直接关系的泛化画像、工作杂事、初识记录或其他弱相关事实。"
        ),
    )
    query = _format_query_template(query_template, {"name": persona_name, "user_id": user_id, "message": message, "history": history})
    body: dict[str, Any] = {
        "query": query,
        "types": _csv(_env(env, "WSD_HINDSIGHT_TYPES", "HINDSIGHT_TYPES", default="world,observation")),
        "budget": _env(env, "WSD_HINDSIGHT_BUDGET", "HINDSIGHT_BUDGET", default="mid"),
        "max_tokens": int(_env(env, "WSD_HINDSIGHT_MAX_TOKENS", "HINDSIGHT_MAX_TOKENS", default="1800")),
    }
    if tags:
        body["tags"] = tags
        body["tags_match"] = tags_match
    query_timestamp = _env(env, "WSD_HINDSIGHT_QUERY_TIMESTAMP", "HINDSIGHT_QUERY_TIMESTAMP")
    if query_timestamp:
        body["query_timestamp"] = query_timestamp
    return body


def _post_hindsight_recall(api_url: str, api_key: str, bank_id: str, body: dict[str, Any], env: Mapping[str, str]) -> list[dict[str, Any]]:
    verify_tls = _env(env, "WSD_HINDSIGHT_VERIFY_TLS", "HINDSIGHT_VERIFY_TLS", default="true").lower() not in {"0", "false", "no"}
    response = requests.post(
        f"{api_url}/v1/default/banks/{bank_id}/memories/recall",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
        verify=verify_tls,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise MemoryRecallError(f"Hindsight recall returned non-JSON response: HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        raise MemoryRecallError(f"Hindsight recall HTTP {response.status_code}: {str(data)[:800]}")
    raw_results = data.get("results") if isinstance(data, Mapping) else None
    if raw_results is None and isinstance(data, list):
        raw_results = data
    if not isinstance(raw_results, list):
        return []
    results = []
    for item in raw_results[:12]:
        if not isinstance(item, Mapping):
            continue
        text = _localize_hindsight_text(str(item.get("text") or item.get("content") or "").strip())
        if not text:
            continue
        results.append(
            {
                "content": text,
                "metadata": item.get("metadata") or {},
                "tags": item.get("tags") or [],
                "id": item.get("id"),
                "type": item.get("type"),
                "source": "hindsight",
            }
        )
    return results


def _localize_hindsight_text(text: str) -> str:
    return (
        text.replace(" | When:", "\n时间：")
        .replace(" | Involving:", "\n相关：")
        .replace(" | Evidence:", "\n证据：")
    )
