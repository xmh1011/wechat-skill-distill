# 云部署指南：Hugging Face Spaces 后端 + Tiiny 静态前端

`wechat-skill-distill` 的聊天网页由两部分组成：

- 前端静态文件：`wechat_skill_distill/web/index.html`、`app.js`、`styles.css`。
- 后端服务：`chat-ui` 提供 `/api/runtime`、`/api/skills`、`/api/chat`，并在服务端保存模型 API key、记忆 API key 和完整 skill。

Tiiny Host 只能放静态前端。完整聊天需要把后端部署到支持 Python 或 Docker 的平台，再让 Tiiny 页面通过 `apiBase` 调用这个后端。

## 方案选择

推荐先用 Hugging Face Spaces：

- 免费 CPU Basic Space 可跑 Docker/Python 后端。
- 自动提供 HTTPS 域名。
- 支持环境变量和 secrets。
- Space 长时间不用会休眠，第一次请求可能较慢，适合个人试用和演示。

Koyeb 当前可能要求绑定信用卡并进入 Pro plan，不适合作为“完全免费、不绑卡”的首选。也可以用 Render、Railway、Fly.io、Cloud Run、VPS 等，只要能运行 Docker 或 Python 长驻服务，并支持 HTTPS 和环境变量。

## 1. 准备后端环境变量

不要把 `.env`、原始聊天记录、`*.chat-memory.skill` 提交到 GitHub。云端部署时用环境变量配置。

模型服务示例：

```bash
WSD_MODEL_PROVIDER=openai
WSD_OPENAI_BASE_URL=https://api.openai.com/v1
WSD_OPENAI_MODEL=gpt-4.1-mini
WSD_OPENAI_API_KEY=...
WSD_MODEL_MAX_TOKENS=800
```

Hindsight 记忆示例：

```bash
WSD_MEMORY_RECALL_BACKEND=hindsight
HINDSIGHT_API_URL=https://cloud.memory.example.com/api
HINDSIGHT_BANK_ID=wechat-memory
HINDSIGHT_API_KEY=...
WSD_HINDSIGHT_TYPES=world,observation
WSD_HINDSIGHT_MAX_TOKENS=3200
```

如果前端在 Tiiny，后端在 Hugging Face Spaces，必须配置 CORS：

```bash
WSD_CORS_ORIGINS=https://your-site.tiiny.site
```

部署验证阶段也可以临时设置：

```bash
WSD_CORS_ORIGINS=*
```

验证通过后建议改回明确域名。

公网后端建议开启访问令牌，避免任何人直接调用 `/api/chat` 消耗你的模型 API：

```bash
WSD_CHAT_AUTH_TOKEN=<生成一个长随机字符串>
```

开启后，前端访问 URL 需要带上：

```text
?accessToken=<同一个随机字符串>
```

## 2. 用环境变量加载私有 skill

云端不能读取你本机的 `generated-chat-skills/朋友.chat-memory.skill`，也不应该把它提交到公开仓库。推荐把 skill 文本 base64 后作为 secret 环境变量注入。

macOS 生成方式：

```bash
base64 -i generated-chat-skills/朋友.chat-memory.skill | tr -d '\n'
```

复制输出到云平台环境变量：

```bash
WSD_SKILL_1_TEXT_BASE64=<上一步输出>
WSD_SKILL_1_FILE_NAME=朋友.chat-memory.skill
WSD_SKILL_1_DISPLAY_NAME=朋友
```

需要多个对象时，继续添加：

```bash
WSD_SKILL_2_TEXT_BASE64=...
WSD_SKILL_2_FILE_NAME=另一个人.chat-memory.skill
WSD_SKILL_2_DISPLAY_NAME=另一个人
```

本地仍然可以用文件方式启动：

```bash
wechat-skill-distill chat-ui \
  --host 127.0.0.1 \
  --port 8765 \
  --env-file .env \
  --skill generated-chat-skills/朋友.chat-memory.skill
```

## 3. 部署到 Hugging Face Spaces

仓库已经包含 `Dockerfile`，默认监听 Hugging Face Spaces 的 `7860` 端口。

基本步骤：

1. 登录 Hugging Face，创建一个 Space。
2. SDK 选择 `Docker`。
3. Hardware 选择免费 `CPU basic`。
4. 把本仓库代码推送到这个 Space 仓库，或在 Space 里导入 GitHub 仓库。
5. 在 Space Settings 的 Variables and secrets 中添加上面的模型、记忆、CORS、访问令牌和 skill 环境变量。
6. 部署完成后得到类似 `https://your-user-your-space.hf.space` 的后端地址。

后端验证：

```bash
curl https://your-user-your-space.hf.space/api/runtime
curl https://your-user-your-space.hf.space/api/skills
```

期望结果：

- `/api/runtime` 返回 `service.configured=true`。
- 如果配置了 Hindsight/Mem0/JSONL，`memory.configured=true`。
- `/api/skills` 能看到对象展示名，但不会泄漏完整 skill、user_id 或文件路径。

## 4. 部署 Tiiny 静态前端

打包前端：

```bash
cd wechat_skill_distill/web
zip -r ../../wechat-skill-distill-web.zip index.html app.js styles.css
```

上传 `wechat-skill-distill-web.zip` 到 Tiiny Host。

访问时把后端地址放到 `apiBase`：

```text
https://your-site.tiiny.site/?apiBase=https%3A%2F%2Fyour-user-your-space.hf.space
```

如果后端设置了 `WSD_CHAT_AUTH_TOKEN`，同时带上 `accessToken`：

```text
https://your-site.tiiny.site/?apiBase=https%3A%2F%2Fyour-user-your-space.hf.space&accessToken=<你的访问令牌>
```

如果你希望不用 query 参数，可以把 Tiiny 上的 `app.js` 前增加一个小配置文件或内联配置：

```html
<script>
  window.WSD_CONFIG = {
    apiBase: "https://your-user-your-space.hf.space",
    accessToken: "<你的访问令牌>"
  };
</script>
<script src="./app.js"></script>
```

## 5. 功能验证清单

完成部署后至少验证：

- 页面标题显示为 skill 的展示名。
- 顶部状态显示“陪伴服务已连接”。
- “云记忆已接入”状态与后端配置一致。
- 发送一句普通问候，能得到回复。
- 问一个记忆里应有的事实，回复能参考记忆，而不是编造。
- 浏览器开发者工具里没有 API key、完整 skill、user_id、原始记忆命中。

## 常见问题

### 页面能打开，但服务未配置

检查后端环境变量是否包含模型 API key 和模型名：

```bash
WSD_OPENAI_API_KEY=...
WSD_OPENAI_MODEL=...
```

### 页面提示无法读取服务端 skill

检查是否配置了 `WSD_SKILL_1_TEXT_BASE64`，并确认 base64 输出没有换行。

### Tiiny 页面调用 Koyeb 后端失败

优先检查 `WSD_CORS_ORIGINS` 是否包含 Tiiny 的完整 origin，例如：

```bash
WSD_CORS_ORIGINS=https://your-site.tiiny.site
```

### 后端能启动，但聊天失败

常见原因是云平台访问不了你的模型服务或记忆服务。内部 OneAPI、公司内网地址、只允许内网访问的 Hindsight 服务，放到公网云平台后可能无法连通。先在云平台日志里看 `/api/chat` 的错误，再确认对应服务是否允许 Koyeb 出网访问。

如果返回 `401`，说明后端设置了 `WSD_CHAT_AUTH_TOKEN`，但前端 URL 没带 `accessToken`，或者 token 不一致。
