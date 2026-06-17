# wechat-skill-distill PRD

## 1. 产品定位

`wechat-skill-distill` 是一个本地优先的聊天记录资产化工具。它把 WeFlow 等工具导出的微信聊天记录转换成三类可复用资产：

1. **纯说话风格 skill**：只描述某个参与者的语言风格，不依赖记忆库。
2. **记忆数据包**：把原始聊天记录规范化后导入 JSONL、Hindsight、Mem0 或通用 HTTP 记忆后端。
3. **带记忆检索的 chat skill**：在说话风格基础上声明 recall 规则，让 agent 必要时检索长期记忆。

产品不是特定聊天对象、特定后端或单次导入脚本，而是一个可扩展 CLI/SDK。普通用户可以照 README 跑通，开发者可以接入新的聊天导出格式和新的记忆产品。

## 2. 调研结论

### 2.1 聊天导出与转换社区

- `wechat-exporter` 的启发：导出工具需要把微信历史转成标准 JSON，并明确平台限制和安装步骤。我们的产品不做微信客户端破解或导出，只消费用户已经合法取得的导出文件。
- `chat-history-manager` 的启发：聊天数据工具应采用 parser/generator 架构，支持多来源、多目标转换，而不是把数据格式写死在单个脚本里。
- `WeClone` 的启发：从聊天记录生成“数字分身”时，用户最关心的是风格一致性、身份边界和使用风险。我们的 MVP 不做模型微调，但需要沉淀可解释的风格 skill 和后续评测能力。

### 2.2 记忆系统社区

- `Mem0` 的启发：记忆产品通常同时提供本地库、自托管和云服务路径，并围绕 user/session/agent 维度管理记忆；我们的 adapter 必须保留 user_id、timestamp、tags、participants 等关键字段。
- `LangMem` 的启发：长期记忆不只是存储，还包括从对话中抽取事实、更新行为提示、热路径搜索和后台整理；我们的路线图需要支持 memory extraction、consolidation、recall policy。
- `Graphiti` 的启发：对真实世界聊天，时间、关系变化和来源 provenance 很关键；我们的 MemoryItem 必须保留 timestamp、source、participant、原文片段和可追踪 metadata。

## 3. 用户角色

- **普通用户**：有微信聊天 JSON，想生成朋友、家人或自己的说话风格 skill。
- **Agent 使用者**：想让 Codex、Claude Code、Cursor、OpenCode 等 agent 在角色扮演时按某人的风格回复。
- **记忆服务集成者**：想把同一份聊天记录导入 Hindsight、Mem0、内部记忆服务或本地 JSONL。
- **数据/产品开发者**：想扩展新的 parser、memory backend、评测规则或导出格式。
- **隐私敏感用户**：需要先在本地 dry-run、审查产物，再决定是否上传到云端。

## 4. 核心场景

### S1 快速生成无记忆风格 skill

用户拿到 WeFlow JSON 后运行：

```bash
wechat-skill-distill extract-skills --input chat.json --out-dir generated-skills --config config.local.json
```

产物：

```text
generated-skills/Participant A.skill
generated-skills/Participant B.skill
```

要求：

- 文件不包含 `## 记忆检索`、API key、memory backend 名称。
- 每个参与者独立，不混入另一个人的姓名、身份或口头禅。
- skill 能说明目标、使用时机、说话风格、真实样本、场景模板、硬边界、自检。

### S2 导入记忆库

用户先本地 dry-run：

```bash
wechat-skill-distill import --backend jsonl --input chat.json --group-by message --output exports/memory.jsonl --dry-run --config config.local.json
```

确认 JSONL 后再切换到云服务：

```bash
wechat-skill-distill import --backend mem0 --input chat.json --group-by day --config config.local.json
wechat-skill-distill import --backend hindsight --input chat.json --group-by day --config config.local.json
```

要求：

- dry-run 不调用远程服务。
- 每条 MemoryItem 至少包含 `content`、`metadata`、`timestamp`、`participants`、`tags`。
- metadata 必须包含 userID、时间戳或分组起止时间、source、chat_type。

### S3 生成带记忆检索的 chat skill

用户运行：

```bash
wechat-skill-distill generate-chat-skills --input chat.json --out-dir generated-chat-skills --memory-backend mem0 --config config.local.json
```

产物：

```text
generated-chat-skills/Participant A.chat-memory.skill
generated-chat-skills/Participant B.chat-memory.skill
```

要求：

- 文件包含 memory backend 的 recall 约定。
- 文件不写入真实 API key，只引用环境变量。
- 当检索不到相关事实时，skill 必须要求 agent 降低确定性或追问，不能编造。

### S4 审查与质量评估

用户希望知道生成结果是否可信：

- `inspect` 在导入前输出消息总数、可导入数、跳过原因、日期范围、参与者和消息类型分布。
- `redact` 在导入云记忆或生成产物前脱敏手机号、邮箱、URL、身份证、银行卡等敏感值，并输出报告。
- `doctor` 检查输入文件、参与者映射、环境变量和输出目录。
- `evaluate-skills` 检查必需章节、文件类型规则、对方身份混入、样本文本泄漏和 userID 标记。
- 后续版本增强隐私风险和记忆字段完整性评估。

### S5 扩展新的来源或后端

开发者希望新增 Telegram、WhatsApp、微信数据库导出、企业微信或自定义 CSV：

- parser 输出统一 `ChatMessage`。
- memory backend 实现统一 `MemoryBackend.write(items)`。
- skill generator 不依赖具体来源。

### S6 本地前端智能陪伴聊天

用户希望在生成 skill 后立即试聊：

```bash
wechat-skill-distill chat-ui --host 127.0.0.1 --port 8765 --env-file .env
```

要求：

- 页面能通过服务启动参数预加载一个或多个 `.skill` / `.chat-memory.skill` 文件。
- 页面不上传本地记忆文件、不展示 raw memory hits；记忆由服务端 runtime recall 后端检索并注入模型上下文。
- 页面提供 persona 选择、模型协议选择、聊天窗口、输入框、转录导出。
- 页面通过本地 server-side proxy 调用模型，浏览器不保存或发送 API key。
- MVP 支持 OpenAI-compatible chat completions、Anthropic Messages API、Gemini generateContent。
- 输入框支持 `Enter` 发送、`Shift+Enter` 换行。
- 后续版本支持流式输出和更完整的记忆质量诊断。

## 5. 信息架构

### 5.1 输入

- WeFlow JSON：当前 MVP 支持。
- participants config：把 `isSend` 或 `senderUsername` 映射到稳定 `user_id` 和展示名。
- `.env`：只保存本地 API key 和后端地址，不提交。
- config JSON：保存参与者、后端 URL、默认输出路径。

### 5.2 中间模型

`ChatMessage`：

- `local_id`
- `timestamp`
- `date`
- `sender_name`
- `user_id`
- `message_type`
- `content`

`MemoryItem`：

- `content`
- `metadata`
- `timestamp`
- `participants`
- `tags`

### 5.3 输出

- `*.skill`：纯风格 skill，无记忆依赖。
- `*.chat-memory.skill`：风格 + recall contract。
- `memory.jsonl`：离线可审查记忆包。
- 后续版本：`profile.json`、`quality-report.json`、`redaction-report.json`。

## 6. 功能需求

### FR1 Parser 与数据规范化

- MVP 支持 WeFlow JSON 的 `messages` 数组。
- 支持文本消息和引用消息；忽略系统消息、图片、语音、视频等不可直接文本化内容。
- 支持 `start_date`、`end_date`。
- 支持通过 `isSend` 或 `senderUsername` 映射参与者。
- 不做硬编码人名替换或特定聊天修正。
- 后续 parser 应注册为插件，输出统一 `ChatMessage`。

### FR2 风格画像提炼

- 每个 userID 独立统计，不跨用户合并。
- 基础指标：消息数、平均长度、短句比例、常见表达、样本句。
- skill 必须避免直接复制整段原文作为默认回复。
- skill 必须包含身份边界、事实边界和隐私边界。
- 后续版本增加：话题分布、时间段习惯、标点/表情倾向、回应模式、情绪承接方式。

### FR3 无记忆 skill

- 命令：`extract-skills`。
- 默认后缀：`.skill`。
- 不包含 `## 记忆检索`。
- 不引用 Hindsight、Mem0、generic HTTP、JSONL recall。
- 适合离线角色风格模拟、提示词库和手动审查。
- skill frontmatter 必须包含稳定 `name`、`user_id` 和 `display_name`。
- 输出文件名必须做文件系统安全转义，不能由展示名或 userID 产生路径穿越、子目录或非法文件名。
- 同名或 slug 碰撞时必须追加稳定短 hash，不能互相覆盖。

### FR4 有记忆 chat skill

- 命令：`generate-chat-skills`。
- 默认后缀：`.chat-memory.skill`。
- 必须包含 memory backend 专属 recall 指南。
- 支持 `jsonl`、`generic-http`、`hindsight`、`mem0`。
- 不写入真实 key，只引用环境变量。
- skill frontmatter 必须包含稳定 `name`、`user_id` 和 `display_name`。
- 输出文件名必须做文件系统安全转义，不能由展示名或 userID 产生路径穿越、子目录或非法文件名。
- 同名或 slug 碰撞时必须追加稳定短 hash，不能互相覆盖。

### FR5 Memory adapter

- MVP 后端：
  - `jsonl`：本地文件，默认 dry-run 目标。
  - `generic-http`：向任意 HTTP endpoint POST 统一 payload。
  - `hindsight`：调用 Hindsight memory bank API。
  - `mem0`：使用 Mem0 Python client；缺少依赖时给出安装提示。
- 支持 `group-by message` 和 `group-by day`。
- 后续版本增加 `session`、`topic`、`semantic-chunk` 分组。

### FR6 Recall contract

- 每种后端都有明确 query 构造、metadata 过滤和无结果策略。
- Hindsight contract 包含 bank、types、tags、conversation tag。
- Mem0 contract 包含 user_id、metadata、source 和 conversation_id。
- Generic HTTP contract 包含 request/response schema 建议。
- JSONL contract 说明宿主运行时或 agent 需要从 JSONL 文件、索引或服务端 recall adapter 检索后再注入上下文。

### FR7 用户体验

- README 提供从安装、配置、示例运行到真实数据导入的完整路径。
- `inspect` 能在导入前输出 raw/importable/skipped 消息数、日期范围、参与者统计、消息类型和跳过原因。
- `inspect --json` 能输出结构化报告，`inspect --output` 能保存 JSON 报告。
- `doctor` 能检查输入文件、消息数、参与者、必要环境变量。
- 命令错误必须指出缺少哪个参数以及如何设置。
- 所有远程写入命令支持先 dry-run。
- 默认示例不依赖用户私人聊天文件。

### FR8 隐私与安全

- `.env`、raw exports、logs、runs、exports、generated output 默认不提交。
- 生成 skill 不包含 API key。
- 不在产品中嵌入特定用户姓名、ID、私人文件路径或云服务 key。
- `redact` 默认提供手机号、邮箱、URL、身份证、银行卡脱敏规则。
- `redact --policy` 支持用户自定义正则规则和 replacement。

### FR9 可测试性

- 单元测试覆盖 parser、skill 分离、memory JSONL 字段。
- CLI 验收覆盖 `doctor`、`extract-skills`、`generate-chat-skills`、`import --dry-run`。
- 后续版本补端到端测试 fixture 和质量报告 golden file。

### FR10 可扩展性

- Parser、backend、skill template 应保持模块边界清晰。
- 新后端不应修改 parser。
- 新 parser 不应修改 memory backend。
- 复杂能力先沉淀到 PRD/roadmap，再进入实现。

### FR11 Chat UI

- 命令：`chat-ui`。
- 默认监听 `127.0.0.1:8765`，支持 `--host` 和 `--port`。
- 支持 `--env-file` 从本地环境文件读取模型服务配置。
- 支持 `--skill <file>` 从服务启动时预加载一个或多个 `.skill` / `.chat-memory.skill`。
- 使用 package 内置静态资源，不要求 Node.js 或前端构建链。
- 前端不提供 skill 文件选择入口；persona 来自服务端启动参数。
- 完整 skill 文本只保存在本地服务端；浏览器不得接收或回传 raw skill 文本。
- `/api/skills` 只返回 persona 摘要和 `skill_id`，`/api/chat` 根据 `skill_id` 在服务端解析并注入完整 skill。
- 服务端 public persona 摘要和 evaluate-skills 必须复用同一套 skill metadata parser，避免 UI 展示名、userID 和评估报告不一致。
- 前端不上传记忆文件、不做浏览器侧检索；JSONL 记忆通过服务端 `JSONL_MEMORY_PATH` 接入。
- 支持 backend-neutral server-side recall：`/api/chat` 可通过 Hindsight、Generic HTTP、Mem0 或 JSONL 在模型调用前自动检索相关记忆。
- `/api/chat` 不向浏览器返回 raw memory hits，只返回召回状态摘要。
- 模型请求前必须过滤明确属于其他 userID 的 memory hits；过滤只基于 metadata、participants 和 user:<id> tags，不基于记忆文本做业务关键词判断。
- recall query 必须包含当前用户原话、最近用户追问和目标 persona；轻量寒暄默认不召回。
- 后端 adapter 默认单 query，并必须保留记忆服务自己的排序；排序和 rerank 交给记忆后端，不在 harness 维护业务词表或二次排序规则。
- Hindsight recall 默认先用 `user:<id>` + `all_strict` 严格检索，无结果再 fallback 到 conversation tags；其他后端使用统一 query/user/persona/history 契约。
- 支持导出模拟聊天 transcript。
- 支持 `openai`、`anthropic`、`gemini` provider。
- 浏览器只调用本地 `/api/chat`，API key 只在 server-side proxy 使用。
- 模型请求必须注入 skill 原文、最近聊天历史和服务端 recall 结果，要求回复符合 skill 风格。
- 事实边界由 `.chat-memory.skill` 和 server-side harness prompt 约束；memory backend adapter 不写业务话题关键词。
- 输入框支持 `Enter` 发送、`Shift+Enter` 换行。
- 模拟内容不写回记忆库。

### FR12 Skill 质量评估

- 命令：`evaluate-skills`。
- 支持一个或多个 skill 文件或目录。
- 可选 `--input` + participant config，用原始聊天记录检查参与者名称混入和样本文本泄漏。
- 检查 `.skill` 不能包含记忆检索章节或后端 key 名称。
- 检查 `.chat-memory.skill` 必须包含 `## 记忆检索`。
- 输出文本报告、`--json` 结构化报告，或 `--output` 保存 JSON。
- 支持 `--fail-on-issue` 作为 CI/自动化质量门禁。

### FR13 Redaction

- 命令：`redact`。
- 输入 WeFlow JSON，输出脱敏后的 JSON。
- 支持 `--report` 保存 redaction report。
- 默认规则覆盖邮箱、手机号、URL、身份证、银行卡样式数字串。
- 支持 `--policy` 加载自定义规则：`rules[].name`、`rules[].pattern`、`rules[].replacement`。
- 报告包含 messages_scanned、messages_changed、total_replacements、replacements_by_rule、changed_messages。

## 7. CLI 设计

```bash
wechat-skill-distill doctor --input chat.json --config config.local.json
wechat-skill-distill weflow-guide
wechat-skill-distill inspect --input chat.json --config config.local.json
wechat-skill-distill redact --input chat.json --output chat.redacted.json --report reports/redaction.json
wechat-skill-distill extract-skills --input chat.json --out-dir generated-skills --config config.local.json
wechat-skill-distill import --backend jsonl --input chat.json --output exports/memory.jsonl --dry-run --config config.local.json
wechat-skill-distill generate-chat-skills --input chat.json --out-dir generated-chat-skills --memory-backend jsonl --config config.local.json
wechat-skill-distill chat-ui --host 127.0.0.1 --port 8765 --env-file .env
wechat-skill-distill evaluate-skills --skills generated-skills generated-chat-skills --input chat.json --config config.local.json
```

后续命令：

```bash
wechat-skill-distill inspect --input chat.json --config config.local.json
wechat-skill-distill evaluate-skills --skills generated-skills --input chat.json
wechat-skill-distill redact --input chat.json --output redacted.json --policy config/redaction.json
wechat-skill-distill init --wizard
```

## 8. 验收标准

### 当前 MVP 必须满足

- `python3 -m unittest discover -s tests` 通过。
- `wechat-skill-distill inspect --input examples/chat.json --config config.example.json` 能输出消息数、日期范围、参与者、消息类型和跳过原因。
- `wechat-skill-distill inspect --input examples/chat.json --config config.example.json --json` 输出合法 JSON。
- `wechat-skill-distill redact --input <json> --output <redacted-json> --report <report-json>` 能输出脱敏 JSON 和报告。
- `wechat-skill-distill doctor --input examples/chat.json --config config.example.json` 能检查输入。
- `wechat-skill-distill extract-skills --input examples/chat.json --out-dir /tmp/wsd/generated-skills --config config.example.json` 生成两个 `.skill`。
- 生成的 `.skill` 不包含 `## 记忆检索`、`HINDSIGHT_API_KEY`、`MEM0_API_KEY`。
- `wechat-skill-distill generate-chat-skills --input examples/chat.json --memory-backend jsonl --out-dir /tmp/wsd/generated-chat-skills --config config.example.json` 生成两个 `.chat-memory.skill`。
- 生成的 `.chat-memory.skill` 包含 `## 记忆检索` 和 `## 事实边界`。
- `wechat-skill-distill import --backend jsonl --input examples/chat.json --output /tmp/wsd/memory.jsonl --dry-run --config config.example.json` 生成 JSONL。
- JSONL 每行包含 `timestamp` 和 `participants` 顶层字段。
- `wechat-skill-distill chat-ui --host 127.0.0.1 --port <free-port> --skill <skill-file>` 能启动本地前端页面并自动加载 persona。
- chat UI 静态资源包含 `index.html`、`app.js`、`styles.css`，安装后可通过 package data 访问。
- `chat-ui` 提供 `/api/runtime`、`/api/skills` 和 `/api/chat`，支持 OpenAI-compatible、Anthropic、Gemini 协议配置。
- `/api/chat` 在 runtime recall 后端配置可用时会先检索记忆，再把命中结果注入模型请求，但不把 raw memory hits 返回给前端。
- 前端输入框支持 `Enter` 发送、`Shift+Enter` 换行，并在对方回复期间展示等待和错误状态。
- `wechat-skill-distill evaluate-skills --skills <generated-skill-dir> --input examples/chat.json --config config.example.json --json` 输出合法 JSON，并能报告 passed/failed/warnings。
- 仓库中不得出现真实 API key、特定私人聊天人名或私人聊天文件依赖。

### 下一阶段目标

- 增加 parser/backend 注册机制。
- 增加更丰富的风格画像 JSON。

## 9. 路线图

### M1 当前 MVP

- WeFlow parser。
- 无记忆 skill 与有记忆 chat-memory skill 分离。
- JSONL、generic HTTP、Hindsight、Mem0 adapter。
- README、config、inspect、doctor、chat UI、evaluate-skills、redact、单元测试。

### M2 产品可用性增强

- 初始化向导。
- profile.json 输出。
- 更明确的错误恢复建议。

### M3 生态扩展

- 多聊天来源 parser。
- 更多记忆后端。
- 本地向量索引。
- 质量评测报告。

### M4 高级记忆能力

- 事实抽取。
- 记忆合并。
- 时间线与关系变化建模。
- Graph/temporal retrieval adapter。

## 10. 非目标

- 不破解微信、不绕过平台安全机制、不自动获取聊天记录。
- 不训练或微调模型。
- 不保证云端记忆后端 API 永远兼容，adapter 需要按后端版本维护。
- 不把模拟聊天内容当事实来源。
