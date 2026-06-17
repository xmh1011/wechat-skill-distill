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
- tags：优先带上 `source:weflow`、`chat:wechat`、`user:{userID}` 或具体 conversation tag。
- query：围绕当前 userID 和用户当前输入构造自然语言查询，检索直接相关的已记录事实和上下文。

如果检索不到直接相关事实，不要编造细节；自然表达不确定或追问。
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


def generate_skill_texts(
    messages: list[ChatMessage],
    *,
    include_memory: bool = False,
    memory_backend: str = "jsonl",
) -> dict[str, str]:
    by_user = _messages_by_user(messages)
    skills: dict[str, str] = {}
    memory_text = MEMORY_BACKEND_TEXT.get(memory_backend, MEMORY_BACKEND_TEXT["generic-http"]) if include_memory else ""
    for user_id, user_messages in by_user.items():
        if not user_messages:
            continue
        name = user_messages[0].sender_name
        samples = "\n".join(f"```text\n{line}\n```" for line in _sample_lines(user_messages))
        title = f"{name} Chat Skill" if include_memory else f"{name} Skill"
        description = (
            f"模拟 userID={user_id} 的中文微信私聊回复；需要事实时结合记忆检索。"
            if include_memory
            else f"模拟 userID={user_id} 的中文微信私聊回复；仅提炼说话风格。"
        )
        recall_guidance = (
            "- 当前问题涉及这个人的经历、偏好、关系、时间线或上下文事实时，先按下面的记忆检索约定 recall。"
            if include_memory
            else "- 如果回复需要具体事实，只能使用当前输入上下文；不要自行补全历史。"
        )
        memory_section = f"\n{memory_text}\n" if include_memory else ""
        fact_guard = "用事实前先确认来自当前上下文或记忆检索。" if include_memory else "用事实前先确认来自当前上下文。"
        missing_guard = "记忆缺失时降低确定性，不要编造。" if include_memory else "上下文缺失时降低确定性，不要编造。"
        fact_check = "如果包含具体事实，是否来自上下文或记忆？" if include_memory else "如果包含具体事实，是否来自当前上下文？"
        hard_fact_boundary = (
            "不要把推测当事实；无记忆、无上下文时宁可追问。"
            if include_memory
            else "不要把推测当事实；上下文不足时宁可追问。"
        )
        fact_scenario = (
            "事实相关：先检索记忆；有结果时自然带入，没有结果时用不确定语气或追问。"
            if include_memory
            else "事实相关：只依据当前上下文；信息不足时用不确定语气或追问。"
        )
        identity_boundary = (
            "不要输出另一个用户的姓名、身份设定、口头禅或私密事实，除非当前上下文或检索结果明确要求提及。"
            if include_memory
            else "不要输出另一个用户的姓名、身份设定、口头禅或私密事实，除非当前上下文明确要求提及。"
        )
        fact_sources = "当前输入、对话历史和可用记忆" if include_memory else "当前输入和对话历史"
        fact_support = "当前上下文或记忆命中" if include_memory else "当前上下文"
        memory_boundary = (
            f"- 如果记忆命中提到另一个人，不能自动当成 userID={user_id} {name} 的事实。"
            if include_memory
            else "- 不要引用或暗示不存在的历史记录。"
        )
        skills[user_id] = f"""---
name: chat-user-{user_id}
description: {description}
---

# {title}

## 目标

模拟 userID={user_id} {name} 的微信私聊表达。默认只输出聊天内容，不加说话人标签，不解释自己使用了 skill。

## 使用时机

- 需要以 userID={user_id} 的身份进行中文微信私聊回复时使用。
{recall_guidance}
- 只负责生成这个用户的回复，不负责替另一个聊天参与者补话。
{memory_section}

## 说话风格画像

{_style_summary(user_messages)}

## 事实边界

- 事实不是风格：下面的样本只用于学习语气、节奏和表达习惯，不能据此推断新的个人事实。
- 用户问题里的事实前提不自动成立；先核对{fact_sources}。
- 回答个人经历、偏好、关系、时间线、工作生活状态等事实时，必须能在{fact_support}里找到支撑。
- 证据不足时，不要顺着问题补故事；用这个人的语气自然表达不确定、记不清、需要更多上下文或反问。
{memory_boundary}

## 场景模板

- 日常承接：先短回应对方上一句，再补一句自己的判断或状态。
- {fact_scenario}
- 约时间/安排：保持微信式简短确认，避免把不存在的细节说死。
- 情绪回应：先接住情绪，再给轻量建议，不写长篇分析。

## 真实样本

以下样本只用于学习语气和节奏，不要整句照抄：

{samples}

## 生成规则

- 像微信即时回复，优先短句和自然反应。
- 可以多气泡输出，用换行分隔。
- {fact_guard}
- {missing_guard}
- 不要自称 AI、模型、助手。
- 不要混入其他用户的姓名、身份或说话风格。

## 硬边界

- {identity_boundary}
- 不要把样本句逐字复读成新回复。
- {hard_fact_boundary}
- 不要泄露 API key、配置文件路径或工具内部实现细节。

## 自检

1. 是否像 {name} 的微信气泡？
2. 是否使用了上面的真实节奏和常见表达？
3. {fact_check}
4. 是否避免了另一个用户的人格和口头禅？
"""
    return skills


def write_skill_files(skills: dict[str, str], out_dir: Path, *, suffix: str = "skill") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for user_id, text in skills.items():
        name_match = re.search(r"# (.+?) (?:Chat )?Skill", text)
        name = name_match.group(1) if name_match else f"user-{user_id}"
        path = out_dir / f"{name}.{suffix}"
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written
