from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

import requests


DEFAULT_BANK_ID = "default-bank"


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
    persona = payload.get("persona") or {}
    persona_name = str(persona.get("name") or "当前人物")
    user_id = str(persona.get("userId") or "").strip()
    skill = str(payload.get("skill") or "")
    api_url = _env(env, "WSD_HINDSIGHT_API_URL", "HINDSIGHT_API_URL", default="https://cloud.memory.bj.baidubce.com/api").rstrip("/")
    api_key = _env(env, "WSD_HINDSIGHT_API_KEY", "HINDSIGHT_API_KEY")
    bank_id = _env(env, "WSD_HINDSIGHT_BANK_ID", "HINDSIGHT_BANK_ID") or _extract_bank_id(skill) or DEFAULT_BANK_ID
    tags = _recall_tags(skill, user_id, env)
    request_body = _recall_payload(message, persona_name, user_id, tags, env)
    results = _post_hindsight_recall(api_url, api_key, bank_id, request_body, env)
    if not results and tags and _env(env, "WSD_HINDSIGHT_DISABLE_TAG_FALLBACK", default="0") != "1":
        fallback_body = _recall_payload(message, persona_name, user_id, [], env)
        results = _post_hindsight_recall(api_url, api_key, bank_id, fallback_body, env)
    return results


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


def _recall_tags(skill: str, user_id: str, env: Mapping[str, str]) -> list[str]:
    configured = _csv(_env(env, "WSD_HINDSIGHT_TAGS", "HINDSIGHT_TAGS"))
    tags = configured or _extract_skill_tags(skill)
    if user_id:
        tags.append(f"user:{user_id}")
    return sorted(set(tags))


def _recall_payload(message: str, persona_name: str, user_id: str, tags: list[str], env: Mapping[str, str]) -> dict[str, Any]:
    query_template = _env(
        env,
        "WSD_HINDSIGHT_QUERY_TEMPLATE",
        "HINDSIGHT_QUERY_TEMPLATE",
        default="围绕{name} userID={user_id}，检索与当前问题相关的已记录事实和上下文：{message}",
    )
    query = query_template.format(name=persona_name, user_id=user_id, message=message)
    body: dict[str, Any] = {
        "query": query,
        "types": _csv(_env(env, "WSD_HINDSIGHT_TYPES", "HINDSIGHT_TYPES", default="world,observation")),
        "budget": _env(env, "WSD_HINDSIGHT_BUDGET", "HINDSIGHT_BUDGET", default="mid"),
        "max_tokens": int(_env(env, "WSD_HINDSIGHT_MAX_TOKENS", "HINDSIGHT_MAX_TOKENS", default="1800")),
    }
    if tags:
        body["tags"] = tags
        body["tags_match"] = _env(env, "WSD_HINDSIGHT_TAGS_MATCH", "HINDSIGHT_TAGS_MATCH", default="any_strict")
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
