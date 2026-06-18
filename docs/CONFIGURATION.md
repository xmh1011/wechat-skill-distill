# 配置指南

本项目主要有两类配置：

- `config.local.json`：告诉工具“聊天里每个人是谁”，以及一些默认输出路径。
- `.env`：保存模型服务和记忆服务的地址、模型名、API key。

两者都只应该保存在本地，不要提交到 Git。

## 1. 参与者配置

WeFlow JSON 里通常有 `isSend`、`senderUsername`、`senderDisplayName`。工具需要把这些字段映射成稳定的 `user_id` 和展示名。

### 最常见：按 `isSend` 映射

很多 WeFlow 导出里：

- `isSend=0` 表示对方。
- `isSend=1` 表示自己。

可以这样写 `config.local.json`：

```json
{
  "participants": {
    "0": { "user_id": "friend", "name": "朋友" },
    "1": { "user_id": "me", "name": "我" }
  }
}
```

`user_id` 建议用稳定英文、数字或下划线，例如 `friend`、`me`、`alice`、`bob_2026`。`name` 是页面和文件里展示的名字，可以用中文。

### 更稳定：按 `senderUsername` 映射

如果导出文件里能看到稳定的 `senderUsername`，也可以这样写：

```json
{
  "participants": {
    "wxid_abcd1234": { "user_id": "friend", "name": "朋友" },
    "wxid_me5678": { "user_id": "me", "name": "我" }
  }
}
```

这种方式比 `isSend` 更适合多来源数据或后续扩展。

### 怎么确认映射对不对

运行：

```bash
wechat-skill-distill inspect --input data/my-chat.json --config config.local.json
```

重点看：

```text
participants:
  - friend (朋友): 1234 messages
  - me (我): 1200 messages
```

如果名字反了，就交换 `0` 和 `1` 的配置，再重新运行。

## 2. 模型服务配置

网页试聊和 recall query planner 需要模型服务。浏览器不会接收这些配置，所有请求都由本地服务端代理。

### OpenAI-compatible

适合 OpenAI、OneAPI、DeepSeek-compatible gateway 等兼容 `/chat/completions` 的服务。

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
```

如果使用内部 OneAPI 网关，把 `WSD_OPENAI_BASE_URL` 和 `WSD_OPENAI_MODEL` 换成你的服务地址和模型名。

### Anthropic

```bash
WSD_MODEL_PROVIDER=anthropic
WSD_ANTHROPIC_BASE_URL=https://api.anthropic.com
WSD_ANTHROPIC_MODEL=claude-3-5-sonnet-latest
WSD_ANTHROPIC_API_KEY=...
```

### Gemini

```bash
WSD_MODEL_PROVIDER=gemini
WSD_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
WSD_GEMINI_MODEL=gemini-1.5-pro
WSD_GEMINI_API_KEY=...
```

### 不建议前端覆盖模型

默认配置：

```bash
WSD_ALLOW_CLIENT_PROVIDER_OVERRIDE=0
WSD_ALLOW_CLIENT_MODEL_OVERRIDE=0
```

保持默认即可。这样浏览器只知道“服务是否已连接”，不知道 provider、model、base URL 或 API key。

## 3. 运行时边界

`chat-ui` 是本地服务端代理模型和记忆服务，浏览器只负责展示和提交用户消息。

- 浏览器只接收 persona 摘要和 skill_id，不接收完整 skill 文本，也不接收本地 skill 文件名，不接收 user_id，不接收常见表达短语。
- 聊天请求只提交 skill_id。聊天 API 不接受浏览器传入 raw skill 或 persona 覆盖；服务端未通过 `--skill` 预加载对象时会拒绝聊天请求。
- 模型 base URL、provider、model 和 API key 只保留在本地服务端，`/api/runtime` 只返回服务是否已连接和云记忆是否接入。
- 浏览器不接收 provider、model、memory backend 名称或 bank_id，不提交 provider 覆盖字段，也不提交模型覆盖字段。
- 聊天响应只返回文本和记忆计数，不返回 provider、model 或 usage。
- 默认不向浏览器返回 provider 或 memory 的原始错误细节；本地排查时才设置 `WSD_DEBUG_ERRORS=1`。
- 多 persona 模拟时，每个 persona 维护独立对话历史和本轮记忆状态；切换对象不会把上一位对象的 history 传给下一位。

输出文件名会从展示名派生并做文件系统安全转义；真实展示名和 user_id 保存在 skill frontmatter。同名或安全化后同名时会追加短 hash 防止覆盖。服务端 persona 摘要和评估报告使用同一套 skill metadata 解析规则，优先使用 frontmatter 的 display_name；user_id 只在服务端解析、召回和评估链路使用，只解析文件开头的 frontmatter block。

## 4. 记忆后端配置

### 只做本地试验：JSONL

先生成 JSONL：

```bash
wechat-skill-distill import \
  --backend jsonl \
  --input data/my-chat.json \
  --output exports/memory.jsonl \
  --dry-run \
  --config config.local.json
```

再配置网页 recall：

```bash
WSD_MEMORY_RECALL_BACKEND=jsonl
JSONL_MEMORY_PATH=exports/memory.jsonl
```

这种方式不需要云服务，适合第一次验证。

### Hindsight

```bash
WSD_MEMORY_RECALL_BACKEND=hindsight
HINDSIGHT_API_URL=https://cloud.memory.example.com/api
HINDSIGHT_BANK_ID=wechat-memory
HINDSIGHT_API_KEY=...
WSD_HINDSIGHT_TYPES=world,observation
WSD_HINDSIGHT_MAX_TOKENS=3200
```

导入：

```bash
wechat-skill-distill import \
  --backend hindsight \
  --input data/my-chat.json \
  --group-by day \
  --config config.local.json
```

### Mem0

先安装可选依赖：

```bash
pip install -e '.[mem0]'
```

配置：

```bash
WSD_MEMORY_RECALL_BACKEND=mem0
MEM0_API_KEY=...
```

导入：

```bash
wechat-skill-distill import \
  --backend mem0 \
  --input data/my-chat.json \
  --group-by message \
  --config config.local.json
```

### 通用 HTTP

适合接公司内部记忆服务。

```bash
WSD_MEMORY_RECALL_BACKEND=generic-http
MEMORY_WRITE_URL=https://memory.example.com/import
MEMORY_RECALL_URL=https://memory.example.com/recall
MEMORY_API_KEY=...
```

写入接口会收到：

```json
{
  "items": [
    {
      "content": "...",
      "metadata": {},
      "tags": []
    }
  ]
}
```

召回接口会收到 `query`、`queries`、`user_id`、`persona`、`history`、`tags`、`limit`、`max_tokens`。

如果配置了运行时记忆后端，`/api/chat` 会在调用模型前召回相关记忆并注入上下文。原始 memory hits 不会返回给浏览器。服务端会按 metadata、participants 和 user:<id> tags 过滤明确属于其他 user 的命中；metadata.userID 和 participants 可以是数组或逗号分隔字符串。JSONL fallback 只使用通用 token 和中文 bigram 匹配，不基于记忆文本做业务关键词过滤。

## 5. Recall 配置建议

默认配置：

```bash
WSD_MEMORY_RECALL_MODE=auto
WSD_MEMORY_RESULT_LIMIT=24
WSD_MEMORY_MAX_TOKENS=3200
WSD_RECALL_QUERY_PLANNER=auto
WSD_MEMORY_QUERY_VARIANTS=1
```

含义：

- 轻量寒暄默认不查记忆。
- 事实问题会根据当前问题、最近追问和目标 persona 构造 query。
- query planner 只整理指代和上下文，不扩展业务关键词。
- 默认单 query，避免 harness 多轮召回后做本地合并排序。
- 排序和 rerank 交给记忆后端。
- Hindsight 和 Mem0 默认只发送一条 query。Hindsight/Mem0 adapter 始终只发送一条 query。

## 6. 推荐配置组合

### 只生成 skill

只需要 `config.local.json`，不用配 `.env`。

### 本地试聊，不接云记忆

`.env` 至少需要模型配置：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
WSD_MEMORY_RECALL_BACKEND=off
```

### 本地 JSONL 记忆试聊

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
WSD_MEMORY_RECALL_BACKEND=jsonl
JSONL_MEMORY_PATH=exports/memory.jsonl
```

### 云记忆陪伴

配置模型服务，再选择 Hindsight、Mem0 或 Generic HTTP 其中一个记忆后端。

## 7. 常见配置错误

### 页面显示“服务未配置”

检查 `.env` 中是否设置了：

- `WSD_MODEL_PROVIDER`
- 对应 provider 的 model
- 对应 provider 的 API key

### 回答事实不准确

先确认记忆是否真的导入：

```bash
wechat-skill-distill import --backend jsonl --input data/my-chat.json --output exports/check.jsonl --dry-run --config config.local.json
```

再确认参与者映射是否正确：

```bash
wechat-skill-distill inspect --input data/my-chat.json --config config.local.json
```

如果云记忆召回不准，优先调整记忆后端自己的检索、rerank 或数据质量；本工具不会维护业务关键词词表做本地 rerank。

### 生成的名字不对

检查 `config.local.json` 的 `name` 字段。文件名会从展示名派生并做安全转义。

### 不想上传隐私数据

使用 JSONL dry-run 和本地 chat-ui 即可；不要配置云记忆后端。对外分享前先运行 `redact`。
