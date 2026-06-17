# 新手入门

这份文档面向第一次使用 `wechat-skill-distill` 的用户。你只需要准备一份 WeFlow 导出的微信私聊 JSON，就可以生成可复用的聊天 skill，并在网页里试聊。

## 这个工具做什么

`wechat-skill-distill` 把聊天记录加工成三类资产：

| 资产 | 文件 | 用途 |
| --- | --- | --- |
| 纯风格 skill | `*.skill` | 只模仿某个人的说话风格，不接记忆库。 |
| 记忆数据 | `memory.jsonl` 或云记忆写入 | 把聊天记录按 message/day 变成可检索的长期记忆。 |
| 带记忆 chat skill | `*.chat-memory.skill` | 同时包含说话风格和记忆检索规则，适合智能陪伴对话。 |

这个项目不负责破解或导出微信数据；它只处理你已经合法导出的 JSON 文件。

## 1. 安装

```bash
git clone https://github.com/xmh1011/wechat-skill-distill.git
cd wechat-skill-distill
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
cp config.example.json config.local.json
```

`.env` 用来放模型服务和记忆服务密钥；`config.local.json` 用来配置聊天参与者。两者都不应该提交到 Git。

## 2. 准备 WeFlow JSON

先用 WeFlow 导出指定私聊为 JSON。详细步骤见 [WEFLOW_EXPORT.md](WEFLOW_EXPORT.md)。

假设文件放在：

```text
data/my-chat.json
```

## 3. 配置参与者

打开 `config.local.json`，把 WeFlow 中的 `isSend` 或 `senderUsername` 映射成稳定 ID 和显示名：

```json
{
  "participants": {
    "0": { "user_id": "friend", "name": "朋友" },
    "1": { "user_id": "me", "name": "我" }
  }
}
```

如果不确定映射是否正确，先跑 inspect：

```bash
wechat-skill-distill inspect --input data/my-chat.json --config config.local.json
```

看输出里的参与者、日期范围、可导入消息数是否符合预期。

## 4. 生成纯风格 skill

```bash
wechat-skill-distill extract-skills \
  --input data/my-chat.json \
  --out-dir generated-skills \
  --config config.local.json
```

产物类似：

```text
generated-skills/朋友.skill
generated-skills/我.skill
```

纯风格 skill 不包含任何记忆后端配置，适合先审查说话风格是否像。

## 5. 生成带记忆的 chat skill

```bash
wechat-skill-distill generate-chat-skills \
  --input data/my-chat.json \
  --out-dir generated-chat-skills \
  --memory-backend jsonl \
  --config config.local.json
```

产物类似：

```text
generated-chat-skills/朋友.chat-memory.skill
generated-chat-skills/我.chat-memory.skill
```

如果你使用 Hindsight、Mem0 或通用 HTTP 记忆服务，把 `--memory-backend` 换成对应值即可。

## 6. 先做本地记忆 dry-run

```bash
wechat-skill-distill import \
  --backend jsonl \
  --input data/my-chat.json \
  --group-by message \
  --output exports/memory.jsonl \
  --dry-run \
  --config config.local.json
```

确认 `exports/memory.jsonl` 没有问题后，再考虑导入云记忆。

## 7. 启动网页试聊

先在 `.env` 中配置模型服务，例如 OpenAI-compatible 网关：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
```

然后启动：

```bash
wechat-skill-distill chat-ui \
  --host 127.0.0.1 \
  --port 8765 \
  --env-file .env \
  --skill generated-chat-skills/朋友.chat-memory.skill
```

打开终端打印的 URL，就能和这个 skill 对应的人物试聊。浏览器不会接收 API key、模型地址、完整 skill 文本或原始记忆命中。

![聊天界面桌面截图](assets/chat-ui-overview.png)

移动窄屏下也可以直接使用：

![聊天界面移动截图](assets/chat-ui-mobile.png)

## 8. 常用检查命令

```bash
wechat-skill-distill doctor --input data/my-chat.json --config config.local.json
wechat-skill-distill evaluate-skills --skills generated-skills generated-chat-skills --input data/my-chat.json --config config.local.json
```

`doctor` 用来检查输入和环境；`evaluate-skills` 用来检查 skill 章节、记忆规则、身份边界和样本质量。

## 9. 安全建议

- 不要提交 `.env`、原始聊天 JSON、`exports/`、`generated-skills/`、`generated-chat-skills/`。
- 导入云记忆前先跑 `--dry-run`。
- 对外分享前先用 `redact` 脱敏。
- 如果 memory 命中不足，skill 应该降低确定性或追问，不应该编造事实。
