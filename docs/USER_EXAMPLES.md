# 用户示例

这份文档按用户目标组织命令。你可以直接找到最接近自己的场景。

## 示例 1：我只想提取一个人的说话风格

适合：先审查风格，不接记忆库，不启动网页。

1. 配置参与者：

```json
{
  "participants": {
    "0": { "user_id": "friend", "name": "朋友" },
    "1": { "user_id": "me", "name": "我" }
  }
}
```

2. 检查聊天文件：

```bash
wechat-skill-distill inspect --input data/my-chat.json --config config.local.json
```

3. 生成 skill：

```bash
wechat-skill-distill extract-skills \
  --input data/my-chat.json \
  --out-dir generated-skills \
  --config config.local.json
```

4. 打开 `generated-skills/朋友.skill` 人工检查。

你会得到一个只描述“朋友”说话风格的 skill，不包含记忆后端和 API key。

## 示例 2：我想做本地智能陪伴试聊

适合：先不接云记忆，只用本地模型服务和生成的 skill 试效果。

1. 生成 chat skill：

```bash
wechat-skill-distill generate-chat-skills \
  --input data/my-chat.json \
  --out-dir generated-chat-skills \
  --memory-backend jsonl \
  --config config.local.json
```

2. 配置 `.env`：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
WSD_MEMORY_RECALL_BACKEND=off
```

3. 启动网页：

```bash
wechat-skill-distill chat-ui \
  --env-file .env \
  --skill generated-chat-skills/朋友.chat-memory.skill \
  --display-name 朋友昵称
```

4. 打开终端输出的 URL。

如果页面显示“服务已连接”，就可以开始试聊。

`--display-name` 只改变页面显示的名字，不改变 skill 里用于模型和记忆召回的真实身份。

## 示例 3：我想用本地 JSONL 记忆试聊

适合：想让回答能引用聊天历史，但暂时不上传云服务。

1. 生成 JSONL 记忆：

```bash
wechat-skill-distill import \
  --backend jsonl \
  --input data/my-chat.json \
  --output exports/memory.jsonl \
  --dry-run \
  --config config.local.json
```

2. 配置 `.env`：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
WSD_MEMORY_RECALL_BACKEND=jsonl
JSONL_MEMORY_PATH=exports/memory.jsonl
```

3. 启动：

```bash
wechat-skill-distill chat-ui \
  --env-file .env \
  --skill generated-chat-skills/朋友.chat-memory.skill
```

当你问“之前我们聊过什么”“你喜欢什么”这类事实问题时，服务端会先查本地 JSONL，再把相关上下文注入模型。

## 示例 4：我想把聊天记录导入 Hindsight

适合：已经有 Hindsight bank，希望网页聊天时从云记忆召回。

1. 配置 `.env`：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...

WSD_MEMORY_RECALL_BACKEND=hindsight
HINDSIGHT_API_URL=https://cloud.memory.example.com/api
HINDSIGHT_BANK_ID=wechat-memory
HINDSIGHT_API_KEY=...
```

2. 先 dry-run 检查本地数据：

```bash
wechat-skill-distill import \
  --backend jsonl \
  --input data/my-chat.json \
  --output exports/check.jsonl \
  --dry-run \
  --config config.local.json
```

3. 确认后写入 Hindsight：

```bash
set -a && source .env && set +a
wechat-skill-distill import \
  --backend hindsight \
  --input data/my-chat.json \
  --group-by day \
  --config config.local.json
```

4. 生成 Hindsight chat skill：

```bash
wechat-skill-distill generate-chat-skills \
  --input data/my-chat.json \
  --out-dir generated-chat-skills \
  --memory-backend hindsight \
  --config config.local.json
```

5. 启动网页：

```bash
wechat-skill-distill chat-ui \
  --env-file .env \
  --skill generated-chat-skills/朋友.chat-memory.skill
```

## 示例 5：我想接公司内部记忆服务

适合：你有自己的 HTTP 写入和召回接口。

1. 配置 `.env`：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://model.example.com/v1
WSD_OPENAI_MODEL=deepseek-v4-flash
WSD_OPENAI_API_KEY=...

WSD_MEMORY_RECALL_BACKEND=generic-http
MEMORY_WRITE_URL=https://memory.example.com/import
MEMORY_RECALL_URL=https://memory.example.com/recall
MEMORY_API_KEY=...
```

2. 导入：

```bash
wechat-skill-distill import \
  --backend generic-http \
  --input data/my-chat.json \
  --group-by day \
  --config config.local.json
```

3. 生成 skill：

```bash
wechat-skill-distill generate-chat-skills \
  --input data/my-chat.json \
  --out-dir generated-chat-skills \
  --memory-backend generic-http \
  --config config.local.json
```

Generic HTTP recall endpoint 需要按 [配置指南](CONFIGURATION.md) 中的字段返回结果。

## 示例 6：我准备对外分享产物

适合：你要把生成的 skill 给别人看，或者把示例放进文档。

1. 先脱敏：

```bash
wechat-skill-distill redact \
  --input data/my-chat.json \
  --output data/my-chat.redacted.json \
  --report reports/redaction.json
```

2. 用脱敏后的文件生成 skill：

```bash
wechat-skill-distill extract-skills \
  --input data/my-chat.redacted.json \
  --out-dir generated-skills \
  --config config.local.json
```

3. 评估：

```bash
wechat-skill-distill evaluate-skills \
  --skills generated-skills \
  --input data/my-chat.redacted.json \
  --config config.local.json \
  --fail-on-issue
```

4. 人工检查：

- 有没有真实姓名、手机号、地址、链接。
- 有没有整段原文被复制。
- 有没有把另一个人的说话风格混进来。
- 有没有 API key 或本地路径。
