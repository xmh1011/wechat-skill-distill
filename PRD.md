# wechat-skill-distill PRD

## 背景

用户希望把 WeFlow 等工具导出的微信私聊记录转成可复用的 agent 资产：一方面提炼每个聊天参与者的说话风格 skill，另一方面把原始聊天记录导入长期记忆库，再生成能在对话时检索记忆的 chat skill。

本版本按通用产品重新组织，不以任何单一记忆后端或特定聊天对象为中心。

## 目标

在当前仓库中提供一套命令行工具和文档，使用户只需要准备聊天导出文件、配置 API 参数，就能完成：

1. 解析 WeFlow 微信聊天导出。
2. 为每个参与者提炼独立的说话风格 skill。
3. 将聊天记录导入 Hindsight、Mem0 或通用 HTTP/JSONL 记忆后端。
4. 生成结合记忆检索约定的 chat skill。
5. 按 README 引导完成安装、配置、试跑、导入和产物检查。

## 非目标

- 不内置破解、绕过或自动化微信客户端导出能力。
- 不替用户申请或管理第三方记忆库账号。
- 不保证所有第三方记忆库私有部署 API 完全一致；通过适配器和通用 HTTP 配置覆盖差异。
- 不把模拟聊天结果当作原始事实，只作为验证 chat skill 行为的辅助工具。

## 用户角色

- **普通用户**：有 WeFlow 导出的 JSON 文件，希望生成两个角色 skill 并导入记忆库。
- **Agent 开发者**：希望把某段聊天记录沉淀成可复用 memory/chat skill。
- **记忆服务集成者**：希望把同一份聊天记录导入 Hindsight、Mem0 或内部记忆服务。

## 用户流程

### 流程 A：安装与配置

1. 克隆或进入仓库。
2. 创建虚拟环境并安装依赖。
3. 复制 `.env.example` 为 `.env`。
4. 按需填写 Hindsight、Mem0 或通用 HTTP 参数；本地 JSONL dry-run 不需要云服务参数。
5. 运行 `wechat-skill-distill doctor` 检查配置和输入文件。

### 流程 B：从聊天记录生成 skill

1. 用户使用 WeFlow 导出微信聊天 JSON。
2. 运行 `wechat-skill-distill extract-skills --input <json> --out-dir skills/`.
3. 工具按参与者拆分消息、统计表达特征、抽取真实示例、生成独立 skill。
4. 用户得到每个参与者一个 `.chat-memory.skill` 文件。

### 流程 C：导入记忆库

1. 运行 `wechat-skill-distill import --backend <backend> --input <json> --config config/local.json`。
2. 工具把聊天记录转成统一 `MemoryItem`。
3. 后端适配器负责提交到目标记忆库。
4. 支持 `--dry-run` 先输出 JSONL 和摘要，不调用远程服务。

### 流程 D：生成带记忆检索的 chat skill

1. 运行 `wechat-skill-distill generate-chat-skills --input <json> --memory-backend <backend> --out-dir skills/`.
2. 工具在说话风格 skill 中加入对应记忆后端的 recall 约定。
3. 产物默认不写入 API key，只引用环境变量。

## 功能需求

### FR1 WeFlow 解析

- 支持读取 WeFlow JSON 中的 `messages`。
- 支持文本消息和引用消息。
- 支持通过 `isSend` 或用户名映射参与者。
- 输出统一字段：`local_id`、`timestamp`、`date`、`sender_name`、`user_id`、`content`、`message_type`。
- 支持过滤起止日期。

### FR2 风格 skill 提炼

- 每个 userID 生成独立 skill 文件。
- skill 不能混入另一个用户的姓名、身份或人格设定。
- skill 包含：目标、使用时机、说话风格、常用语、场景模板、硬边界、自检。
- 基于真实聊天记录统计：短句比例、常用词、表情/语气词、消息长度、话题样本。
- 支持输出 memory-aware 版本：包含 Hindsight、Mem0 或通用 HTTP recall 约定。

### FR3 记忆导入

- 统一内存模型：`MemoryItem(content, metadata, tags, timestamp, participants)`。
- 支持后端：
  - `hindsight`：调用 Hindsight bank memories API。
  - `mem0`：优先使用已安装的 Mem0 Python client；未安装时给出明确安装提示。
  - `jsonl`：本地 JSONL，作为通用离线交换格式。
  - `generic-http`：按配置向任意 HTTP endpoint POST JSON payload。
- 支持按 `message`、`day` 分组。
- metadata 必须包含参与者 userID 和消息时间戳或分组起止时间。
- 所有 API key 只能来自环境变量或本地配置，不能写入生成文件。

### FR4 Chat skill 生成

- 根据风格 skill + 记忆后端配置生成 `.chat-memory.skill`。
- skill 中说明何时 recall、如何构造 query、如何处理无记忆结果。
- 对 Hindsight 使用 `types=["world","observation"]`、conversation tag、bank ID。
- 对 Mem0 使用 user_id / metadata 约定。
- 对 generic HTTP 说明 request/response 字段映射。

### FR5 用户友好与开箱即用

- README 包含从安装到产物检查的完整路径。
- `.env.example` 和 `config.example.json` 覆盖常见参数。
- 提供 `doctor` 命令检查依赖、输入文件、环境变量。
- 每个写远程服务的命令都有 `--dry-run`。
- 错误信息要指出缺少哪个参数、如何设置。

## 数据与隐私要求

- 默认不提交聊天原文、日志、API key 和 `.env`。
- 生成产物中的 API key 必须使用环境变量引用。
- logs/runs/exports 默认进入 `.gitignore`。
- 导入远程记忆库前必须支持 dry-run。

## 验收标准

- `python3 -m unittest discover -s tests` 通过。
- `wechat-skill-distill doctor --input examples/chat.json --config config.example.json` 能检查输入。
- `wechat-skill-distill extract-skills --input examples/chat.json --out-dir generated-skills --memory-backend jsonl --config config.example.json` 生成两个独立 skill。
- `wechat-skill-distill import --backend jsonl --input examples/chat.json --output exports/memory.jsonl --dry-run --config config.example.json` 生成 JSONL。
- `wechat-skill-distill generate-chat-skills --input examples/chat.json --memory-backend jsonl --out-dir generated-chat-skills --config config.example.json` 生成 memory-aware skill。
- README 中的 quickstart 能从空虚拟环境跑通本地 dry-run。

## 里程碑

1. PRD 和配置模板。
2. 统一 parser、skill generator、memory adapter。
3. CLI 命令与 dry-run。
4. README 完整安装使用引导。
5. 单元测试与验收命令。
