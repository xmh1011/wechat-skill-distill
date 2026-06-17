from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Mapping

import requests


PROVIDERS = ("openai", "anthropic", "gemini")


class ModelConfigError(RuntimeError):
    pass


class ModelCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    base_url: str
    api_key: str

    @property
    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "configured": bool(self.api_key and self.model),
        }


def load_env_file(path: str | os.PathLike[str] | None) -> None:
    if not path:
        return
    env_path = os.fspath(path)
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _env(env: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return default


def provider_config(provider: str, env: Mapping[str, str] | None = None) -> ProviderConfig:
    current_env = env or os.environ
    normalized = provider.lower().replace("_", "-")
    if normalized in {"openai-compatible", "openai-compatible-chat"}:
        normalized = "openai"
    if normalized not in PROVIDERS:
        raise ModelConfigError(f"unsupported provider: {provider}")

    if normalized == "openai":
        return ProviderConfig(
            provider="openai",
            model=_env(current_env, "WSD_OPENAI_MODEL", "OPENAI_MODEL", "WSD_MODEL_NAME", "MODEL_NAME"),
            base_url=_env(current_env, "WSD_OPENAI_BASE_URL", "OPENAI_BASE_URL", "WSD_MODEL_BASE_URL", "MODEL_BASE_URL", default="https://api.openai.com/v1"),
            api_key=_env(current_env, "WSD_OPENAI_API_KEY", "OPENAI_API_KEY", "WSD_MODEL_API_KEY", "MODEL_API_KEY"),
        )
    if normalized == "anthropic":
        return ProviderConfig(
            provider="anthropic",
            model=_env(current_env, "WSD_ANTHROPIC_MODEL", "ANTHROPIC_MODEL", "WSD_MODEL_NAME", "MODEL_NAME"),
            base_url=_env(current_env, "WSD_ANTHROPIC_BASE_URL", "ANTHROPIC_BASE_URL", default="https://api.anthropic.com"),
            api_key=_env(current_env, "WSD_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        )
    return ProviderConfig(
        provider="gemini",
        model=_env(current_env, "WSD_GEMINI_MODEL", "GEMINI_MODEL", "GOOGLE_MODEL", "WSD_MODEL_NAME", "MODEL_NAME"),
        base_url=_env(current_env, "WSD_GEMINI_BASE_URL", "GEMINI_BASE_URL", "GOOGLE_AI_BASE_URL", default="https://generativelanguage.googleapis.com/v1beta"),
        api_key=_env(current_env, "WSD_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )


def runtime_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    current_env = env or os.environ
    providers = [provider_config(provider, current_env).public_dict for provider in PROVIDERS]
    requested_default = _env(current_env, "WSD_MODEL_PROVIDER", "MODEL_PROVIDER", default="")
    if requested_default:
        default_provider = requested_default.lower().replace("_", "-")
        if default_provider.startswith("openai-compatible"):
            default_provider = "openai"
    else:
        configured = next((item["provider"] for item in providers if item["configured"]), "")
        default_provider = configured or "openai"
    return {
        "default_provider": default_provider,
        "providers": providers,
    }


def build_companion_prompt(payload: Mapping[str, Any]) -> str:
    persona = payload.get("persona") or {}
    persona_name = persona.get("name") or "当前 persona"
    user_id = persona.get("userId") or "-"
    skill_text = str(payload.get("skill") or "").strip()
    memory_hits = payload.get("memory_hits") or []
    memory_limit = int(_env(os.environ, "WSD_COMPANION_MEMORY_LIMIT", "COMPANION_MEMORY_LIMIT", default="48"))
    hit_lines = []
    for index, hit in enumerate(memory_hits[:memory_limit], start=1):
        if isinstance(hit, Mapping):
            content = str(hit.get("content") or "").strip()
            metadata = hit.get("metadata") or {}
            timestamp = metadata.get("timestamp") if isinstance(metadata, Mapping) else ""
            prefix = f"{index}. "
            if timestamp:
                prefix += f"[{timestamp}] "
            hit_lines.append(prefix + content)
        else:
            hit_lines.append(f"{index}. {hit}")
    hit_text = "\n".join(line for line in hit_lines if line.strip()) or "无相关记忆命中。"
    return f"""你是一个“蒸馏聊天 skill + 智能陪伴系统”的对话 agent。

当前你要模拟的人：{persona_name}
当前 userID：{user_id}

必须遵守：
- 严格根据下方 skill 模仿说话风格、语气、节奏、常用表达和边界。
- 默认只输出一条自然聊天回复，不加说话人标签，不解释你正在使用 skill。
- 使用中文微信私聊语气，像真实聊天，不要写成报告、总结、客服话术或长篇建议。
- 事实不是风格：skill 样本只用于学习语气，不能据此推断新的个人事实。
- 需要事实时优先使用“记忆命中”；命中由云记忆服务按相关性返回，本地不重排，只使用与当前人物和当前问题直接相关的命中。
- 不要默认第一条命中就是答案；回答事实问题前先通读全部命中，找包含明确谓词、主体和取值的直接陈述。
- 回答职业、公司、学校、学历、关系、地点等身份事实时，只能引用记忆命中里的直接陈述；如果只有间接线索，就自然说“只记得大概线索/不能说死”。
- 用户问题里的事实前提不自动成立。只有当前输入、对话历史、skill 明示配置或记忆命中能支撑时，才可以顺着该前提回答。
- 如果记忆命中为空，或命中内容不能支撑当前问题，必须自然表达不确定、记不清或追问，不要编造或写故事补空白。
- 如果记忆命中同时有强弱证据，优先使用更具体、能直接回答问题的那条；不要被泛泛工作动态、初识记录、玩笑称呼或他人经历带跑。
- 如果信息不足，可以自然地追问或降低确定性。
- 可以温和陪伴，但不要越界承诺、诊断或替用户做重大决定。

## Skill
{skill_text or "未提供 skill。"}

## 记忆命中
{hit_text}
"""


def build_recall_query_planner_prompt() -> str:
    return """你是云记忆检索 query planner。你的任务是把用户当前问题改写成少量 recall 查询，不回答问题。

必须遵守：
- 保留目标人物姓名和 userID。
- 可以使用同义词、上位词、相关说法来提高召回，但不能加入输入中没有出现的具体公司、学校、地点、人名、产品、事件。
- 不要只复述用户原话；至少一条 query 要拆成检索词，覆盖问题隐含的抽象属性名、常见记录字段和可能的说法。
- 只能补充抽象字段词，不能补充具体取值。抽象字段词用于查找事实，不能被当作事实答案。
- 不要编造事实，不要根据常识补全。
- 每条 query 都应短而具体，优先能帮助云记忆召回直接事实证据。
- 只输出 JSON 数组，包含 1-3 个字符串；不要输出解释、Markdown 或代码块。
"""


def generate_recall_query_variants(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> list[str]:
    current_env = env or os.environ
    requested_provider = str(payload.get("provider") or _env(current_env, "WSD_MODEL_PROVIDER", "MODEL_PROVIDER", default="openai"))
    config = provider_config(requested_provider, current_env)
    if not config.api_key or not config.model:
        return []
    persona = payload.get("persona") or {}
    persona_name = str(persona.get("name") or "当前人物")
    user_id = str(persona.get("userId") or "-")
    message = str(payload.get("message") or "").strip()
    history = str(payload.get("history") or "无").strip() or "无"
    user_prompt = f"""目标人物：{persona_name}
userID：{user_id}
当前用户原话：{message}
最近用户追问：
{history}
"""
    text, _ = _call_text_model(config, build_recall_query_planner_prompt(), user_prompt, current_env, max_tokens=320, temperature=0)
    return _parse_query_variants(text, persona_name, user_id)


def _parse_query_variants(text: str, persona_name: str, user_id: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed: Any
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = [line.strip("- 0123456789.、\t ") for line in cleaned.splitlines() if line.strip()]
    if not isinstance(parsed, list):
        return []
    prefix = f"{persona_name} userID={user_id}"
    queries = []
    seen = set()
    for item in parsed:
        query = re.sub(r"\s+", " ", str(item or "").strip())
        if not query:
            continue
        if persona_name not in query and user_id not in query:
            query = f"{prefix} {query}"
        query = query[:160].strip()
        if query and query not in seen:
            queries.append(query)
            seen.add(query)
        if len(queries) >= 3:
            break
    return queries


def _clean_history(history: Any) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    if not isinstance(history, list):
        return cleaned
    for item in history[-16:]:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if text:
            cleaned.append({"role": role, "content": text[:2000]})
    return cleaned


def _latest_user_message(payload: Mapping[str, Any]) -> str:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ModelConfigError("message is required")
    return message


def _temperature(env: Mapping[str, str]) -> float | None:
    value = _env(env, "WSD_MODEL_TEMPERATURE", "MODEL_TEMPERATURE")
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ModelConfigError("MODEL_TEMPERATURE must be a number") from exc


def _max_tokens(env: Mapping[str, str], default: int = 800) -> int:
    value = _env(env, "WSD_MODEL_MAX_TOKENS", "MODEL_MAX_TOKENS")
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ModelConfigError("MODEL_MAX_TOKENS must be an integer") from exc


def _call_text_model(
    config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    env: Mapping[str, str],
    *,
    max_tokens: int,
    temperature: float | None = None,
) -> tuple[str, Mapping[str, Any]]:
    if config.provider == "openai":
        body: dict[str, Any] = {
            "model": config.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        response = requests.post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        raw = _response_json(response)
        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelCallError("OpenAI-compatible response did not include choices[0].message.content") from exc
        return str(text), raw
    if config.provider == "anthropic":
        body = {
            "model": config.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if temperature is not None:
            body["temperature"] = temperature
        response = requests.post(
            f"{config.base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": _env(env, "WSD_ANTHROPIC_VERSION", "ANTHROPIC_VERSION", default="2023-06-01"),
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        raw = _response_json(response)
        try:
            text = "".join(part.get("text", "") for part in raw["content"] if part.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise ModelCallError("Anthropic response did not include text content") from exc
        return text, raw
    model_name = config.model if config.model.startswith("models/") else f"models/{config.model}"
    generation_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
    if temperature is not None:
        generation_config["temperature"] = temperature
    response = requests.post(
        f"{config.base_url.rstrip('/')}/{model_name}:generateContent",
        headers={"x-goog-api-key": config.api_key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": generation_config,
        },
        timeout=60,
    )
    raw = _response_json(response)
    try:
        parts = raw["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelCallError("Gemini response did not include candidates[0].content.parts text") from exc
    return text, raw


def generate_chat_reply(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> dict[str, Any]:
    current_env = env or os.environ
    requested_provider = str(payload.get("provider") or _env(current_env, "WSD_MODEL_PROVIDER", "MODEL_PROVIDER", default="openai"))
    config = provider_config(requested_provider, current_env)
    model_override = str(payload.get("model") or "").strip()
    if model_override:
        config = ProviderConfig(config.provider, model_override, config.base_url, config.api_key)
    if not config.api_key:
        raise ModelConfigError(f"{config.provider} API key is not configured")
    if not config.model:
        raise ModelConfigError(f"{config.provider} model is not configured")

    if config.provider == "openai":
        text, raw = _call_openai(config, payload, current_env)
    elif config.provider == "anthropic":
        text, raw = _call_anthropic(config, payload, current_env)
    elif config.provider == "gemini":
        text, raw = _call_gemini(config, payload, current_env)
    else:
        raise ModelConfigError(f"unsupported provider: {config.provider}")
    return {
        "text": text.strip(),
        "provider": config.provider,
        "model": config.model,
        "usage": raw.get("usage") if isinstance(raw, Mapping) else None,
    }


def _call_openai(config: ProviderConfig, payload: Mapping[str, Any], env: Mapping[str, str]) -> tuple[str, Mapping[str, Any]]:
    system_prompt = build_companion_prompt(payload)
    messages = [{"role": "system", "content": system_prompt}, *_clean_history(payload.get("history")), {"role": "user", "content": _latest_user_message(payload)}]
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
    }
    temperature = _temperature(env)
    if temperature is not None:
        body["temperature"] = temperature
    max_tokens = _max_tokens(env)
    if max_tokens:
        body["max_tokens"] = max_tokens
    response = requests.post(
        f"{config.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    raw = _response_json(response)
    try:
        text = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelCallError("OpenAI-compatible response did not include choices[0].message.content") from exc
    return str(text), raw


def _call_anthropic(config: ProviderConfig, payload: Mapping[str, Any], env: Mapping[str, str]) -> tuple[str, Mapping[str, Any]]:
    body: dict[str, Any] = {
        "model": config.model,
        "max_tokens": _max_tokens(env),
        "system": build_companion_prompt(payload),
        "messages": [*_clean_history(payload.get("history")), {"role": "user", "content": _latest_user_message(payload)}],
    }
    response = requests.post(
        f"{config.base_url.rstrip('/')}/v1/messages",
        headers={
            "x-api-key": config.api_key,
            "anthropic-version": _env(env, "WSD_ANTHROPIC_VERSION", "ANTHROPIC_VERSION", default="2023-06-01"),
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    raw = _response_json(response)
    try:
        text = "".join(part.get("text", "") for part in raw["content"] if part.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise ModelCallError("Anthropic response did not include text content") from exc
    return text, raw


def _call_gemini(config: ProviderConfig, payload: Mapping[str, Any], env: Mapping[str, str]) -> tuple[str, Mapping[str, Any]]:
    contents = []
    for item in _clean_history(payload.get("history")):
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})
    contents.append({"role": "user", "parts": [{"text": _latest_user_message(payload)}]})
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": build_companion_prompt(payload)}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": _max_tokens(env)},
    }
    temperature = _temperature(env)
    if temperature is not None:
        body["generationConfig"]["temperature"] = temperature
    model_name = config.model if config.model.startswith("models/") else f"models/{config.model}"
    response = requests.post(
        f"{config.base_url.rstrip('/')}/{model_name}:generateContent",
        headers={"x-goog-api-key": config.api_key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    raw = _response_json(response)
    try:
        parts = raw["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelCallError("Gemini response did not include candidates[0].content.parts text") from exc
    return text, raw


def _response_json(response: requests.Response) -> Mapping[str, Any]:
    try:
        raw = response.json()
    except ValueError as exc:
        raise ModelCallError(f"model service returned non-JSON response: HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        message = raw.get("error") if isinstance(raw, Mapping) else None
        if isinstance(message, Mapping):
            detail = message.get("message") or message
        else:
            detail = message or raw
        raise ModelCallError(f"model service error: HTTP {response.status_code}: {detail}")
    return raw
