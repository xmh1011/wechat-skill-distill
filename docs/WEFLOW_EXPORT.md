# WeFlow 导出教程

本项目消费 WeFlow 导出的 JSON 文件。WeFlow 本身是独立项目，不属于本仓库。

## WeFlow 仓库

- GitHub: <https://github.com/hicccc77/WeFlow>
- 官方 README 说明：WeFlow 是本地微信聊天记录查看、分析与导出工具。
- 官方 README 当前说明 WeFlow 支持微信 4.0 及以上版本，并支持把聊天记录导出为 JSON、HTML、TXT、Excel、CSV、PGSQL 等格式。

WeFlow 的下载入口、安装包和界面可能随版本变化，请以 WeFlow 仓库 README 和最新发布说明为准。

## 导出前准备

1. 确认你有权处理这份聊天记录。
2. 在本机安装并打开微信。
3. 安装 WeFlow，并按 WeFlow 提示完成本地数据读取。
4. 优先选择私聊会话，而不是群聊、公众号或服务号。
5. 导出格式选择 JSON。

## 推荐导出步骤

WeFlow UI 可能随版本调整，下面是通用路径：

1. 打开 WeFlow。
2. 在聊天或私聊列表里找到目标联系人。
3. 进入该会话，确认能看到聊天记录。
4. 点击导出或消息导出。
5. 格式选择 JSON。
6. 保存到本项目目录外的安全位置，例如：

```text
~/Documents/wechat-exports/friend-chat.json
```

7. 复制一份到本项目本地 `data/` 目录做处理：

```bash
mkdir -p data
cp ~/Documents/wechat-exports/friend-chat.json data/my-chat.json
```

`data/` 已在 `.gitignore` 中，默认不会被提交。

## 导出后检查

先运行：

```bash
wechat-skill-distill inspect --input data/my-chat.json --config config.local.json
```

重点看：

- 日期范围是否符合导出的会话。
- `raw` 消息数是否接近你的预期。
- `importable` 消息数是否过低。
- 参与者名称和 `isSend` 映射是否正确。
- 跳过原因里是否大量出现非文本消息。

如果参与者反了，改 `config.local.json` 的 `participants` 映射后重新运行。

## 常见问题

### 导出的不是 JSON

重新从 WeFlow 导出，并选择 JSON 格式。这个项目当前 MVP 不直接消费 HTML、Excel 或 CSV。

### 只有一方消息

通常是参与者映射或导出范围不对。先看 `inspect` 输出里的 participants，再调整 `config.local.json`。

### 图片、语音、视频没有进入 skill

当前项目主要处理可文本化消息。图片、语音、视频等非文本内容会被跳过或只保留可解析文本。

### 担心隐私

先运行本地脱敏：

```bash
wechat-skill-distill redact \
  --input data/my-chat.json \
  --output data/my-chat.redacted.json \
  --report reports/redaction.json
```

之后用脱敏文件继续生成 skill 或 dry-run 记忆。
