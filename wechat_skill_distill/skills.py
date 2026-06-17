from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re

from .models import ChatMessage


MEMORY_BACKEND_TEXT = {
    "hindsight": """## 记忆检索

当回复需要具体事实、偏好、经历、时间线或关系上下文时，先检索 Hindsight。

- API：`HINDSIGHT_API_URL`
- Bank：`HINDSIGHT_BANK_ID`
- Key：`HINDSIGHT_API_KEY`
- Endpoint：`POST /v1/default/banks/{bank_id}/memories/recall`
- types：`["world", "observation"]`
- query：围绕当前 userID 的事实、偏好、习惯、工作状态、情绪状态、关系动态检索。

不要把 key 写入 skill；只引用环境变量。""",
    "mem0": """## 记忆检索

当回复需要具体事实、偏好、经历、时间线或关系上下文时，先检索 Mem0。

- Key：`MEM0_API_KEY`
- user_id：当前 skill 对应的 userID
- metadata：应包含 `source=wechat`、`conversation_id`

如果检索不到相关事实，不要编造细节。""",
    "generic-http": """## 记忆检索

当回复需要具体事实、偏好、经历、时间线或关系上下文时，调用通用 HTTP recall endpoint。

- URL：`MEMORY_RECALL_URL`
- Key：`MEMORY_API_KEY`
- 请求字段建议：`query`、`user_id`、`tags`、`max_tokens`
- 响应字段建议：`results[].text`

如果接口不可用或无结果，不要编造细节。""",
    "jsonl": """## 记忆检索

本 skill 对应离线 JSONL 记忆产物。运行时如需事实，应由宿主 agent 先在 JSONL 或索引中检索相关记录，再把结果放入上下文。

如果没有检索结果，不要编造细节。""",
}


def _messages_by_user(messages: list[ChatMessage]) -> dict[str, list[ChatMessage]]:
    result: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        result[message.user_id].append(message)
    return dict(result)


def _common_phrases(user_messages: list[ChatMessage], limit: int = 16) -> list[str]:
    counter: Counter[str] = Counter()
    for message in user_messages:
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_\[\]]{1,12}|[？?！!。~]+", message.content):
            if token.strip() and token not in {"的", "了", "我", "你", "是", "这", "那"}:
                counter[token] += 1
    return [token for token, _ in counter.most_common(limit)]


def _sample_lines(user_messages: list[ChatMessage], limit: int = 10) -> list[str]:
    short = [m.content for m in user_messages if 2 <= len(m.content) <= 80]
    if not short:
        short = [m.content for m in user_messages[:limit]]
    if len(short) <= limit:
        return short
    step = (len(short) - 1) / (limit - 1)
    return [short[round(i * step)] for i in range(limit)]


def _style_summary(user_messages: list[ChatMessage]) -> str:
    lengths = [len(m.content) for m in user_messages] or [0]
    avg_len = sum(lengths) / len(lengths)
    short_ratio = sum(1 for length in lengths if length <= 20) / len(lengths)
    return f"- 平均消息长度约 {avg_len:.1f} 字；短消息占比约 {short_ratio:.0%}。\n- 常见表达：{'、'.join(_common_phrases(user_messages)) or '样本不足'}。"


def generate_skill_texts(messages: list[ChatMessage], *, memory_backend: str = "hindsight") -> dict[str, str]:
    by_user = _messages_by_user(messages)
    skills: dict[str, str] = {}
    memory_text = MEMORY_BACKEND_TEXT.get(memory_backend, MEMORY_BACKEND_TEXT["generic-http"])
    for user_id, user_messages in by_user.items():
        if not user_messages:
            continue
        name = user_messages[0].sender_name
        samples = "\n".join(f"```text\n{line}\n```" for line in _sample_lines(user_messages))
        skills[user_id] = f"""---
name: chat-user-{user_id}
description: 模拟 userID={user_id} 的中文微信私聊回复；需要事实时结合记忆检索。
---

# {name} Chat Skill

## 目标

模拟 userID={user_id} {name} 的微信私聊表达。默认只输出聊天内容，不加说话人标签，不解释自己使用了 skill 或记忆。

{memory_text}

## 说话风格画像

{_style_summary(user_messages)}

## 真实样本

以下样本只用于学习语气和节奏，不要整句照抄：

{samples}

## 生成规则

- 像微信即时回复，优先短句和自然反应。
- 可以多气泡输出，用换行分隔。
- 用事实前先确认来自当前上下文或记忆检索。
- 记忆缺失时降低确定性，不要编造。
- 不要自称 AI、模型、助手。
- 不要混入其他用户的姓名、身份或说话风格。

## 自检

1. 是否像 {name} 的微信气泡？
2. 是否使用了上面的真实节奏和常见表达？
3. 如果包含具体事实，是否来自上下文或记忆？
4. 是否避免了另一个用户的人格和口头禅？
"""
    return skills


def write_skill_files(skills: dict[str, str], out_dir: Path, *, suffix: str = "chat-memory.skill") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for user_id, text in skills.items():
        name_match = re.search(r"# (.+?) Chat Skill", text)
        name = name_match.group(1) if name_match else f"user-{user_id}"
        path = out_dir / f"{name}.{suffix}"
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written
