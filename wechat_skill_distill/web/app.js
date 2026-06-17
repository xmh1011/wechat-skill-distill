const state = {
  personas: [],
  activeId: "",
  memoryRows: [],
  transcript: [],
  runtime: { default_provider: "openai", providers: [] },
  busy: false
};

const els = {
  skillFiles: document.getElementById("skillFiles"),
  memoryFile: document.getElementById("memoryFile"),
  providerSelect: document.getElementById("providerSelect"),
  modelInput: document.getElementById("modelInput"),
  modelHint: document.getElementById("modelHint"),
  personaSelect: document.getElementById("personaSelect"),
  modeValue: document.getElementById("modeValue"),
  userIdValue: document.getElementById("userIdValue"),
  sampleCountValue: document.getElementById("sampleCountValue"),
  memoryCountValue: document.getElementById("memoryCountValue"),
  styleTokens: document.getElementById("styleTokens"),
  memoryHits: document.getElementById("memoryHits"),
  chatLog: document.getElementById("chatLog"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
  loadDemo: document.getElementById("loadDemo"),
  clearChat: document.getElementById("clearChat"),
  exportChat: document.getElementById("exportChat"),
  appTitle: document.getElementById("appTitle"),
  brandMark: document.querySelector(".brand-mark"),
  runtimeStatus: document.getElementById("runtimeStatus"),
  conversationTitle: document.getElementById("conversationTitle"),
  conversationSub: document.getElementById("conversationSub"),
  typingStatus: document.getElementById("typingStatus"),
  statePills: document.getElementById("statePills"),
  messageTemplate: document.getElementById("messageTemplate")
};

const demoSkill = `---
name: chat-user-participant_b
description: 模拟 userID=participant_b 的中文微信私聊回复；需要事实时结合记忆检索。
---

# Participant B Chat Skill

## 使用时机

- 需要以 userID=participant_b 的身份进行中文微信私聊回复时使用。

## 记忆检索

本 skill 对应离线 JSONL 记忆产物。运行时如需事实，应由宿主 agent 先在 JSONL 或索引中检索相关记录，再把结果放入上下文。

## 事实边界

- 事实不是风格：样本只用于学习语气，不能据此推断新的个人事实。
- 用户问题里的事实前提不自动成立；证据不足时自然表达不确定或追问。

## 说话风格画像

- 平均消息长度约 13.0 字；短消息占比约 100%。
- 常见表达：可以、先把范围卡住、不然越写越散、明天再看也行、别硬撑。

## 真实样本

\`\`\`text
可以，先把范围卡住，不然越写越散
\`\`\`
\`\`\`text
明天再看也行，别硬撑
\`\`\``;

const demoMemory = [
  {
    content: "2026-04-18T21:31:40+08:00 userID=participant_b Participant B: 明天再看也行，别硬撑",
    metadata: { userID: "participant_b", timestamp: "2026-04-18T21:31:40+08:00" },
    tags: ["source:weflow", "chat:wechat", "user:participant_b"]
  }
];

function parseSkill(text, fileName = "skill") {
  const titleMatch = text.match(/^#\s+(.+?)\s+(Chat\s+)?Skill\s*$/m);
  const userMatch = text.match(/userID=([^\s，。`]+)/);
  const commonLine = text.match(/常见表达：([^\n]+)/);
  const samples = [...text.matchAll(/```text\n([\s\S]*?)\n```/g)].map((match) => match[1].trim()).filter(Boolean);
  const phrases = commonLine ? commonLine[1].replace(/[。.;；]\s*$/, "").split(/[、,，]/).map((item) => item.trim()).filter(Boolean) : [];
  const name = titleMatch ? titleMatch[1].trim() : fileName.replace(/\.(chat-memory\.)?skill$/i, "");
  const id = `${userMatch ? userMatch[1] : name}-${Math.random().toString(16).slice(2)}`;
  return {
    id,
    name,
    userId: userMatch ? userMatch[1] : "-",
    memoryAware: text.includes("## 记忆检索"),
    phrases,
    samples,
    raw: text
  };
}

function providerByName(name) {
  return state.runtime.providers.find((provider) => provider.provider === name) || null;
}

function renderProviders() {
  els.providerSelect.innerHTML = "";
  const providers = state.runtime.providers.length ? state.runtime.providers : [
    { provider: "openai", model: "", configured: false },
    { provider: "anthropic", model: "", configured: false },
    { provider: "gemini", model: "", configured: false }
  ];
  for (const provider of providers) {
    const option = document.createElement("option");
    option.value = provider.provider;
    option.textContent = `${provider.provider}${provider.configured ? "" : "（未配置）"}`;
    els.providerSelect.appendChild(option);
  }
  els.providerSelect.value = state.runtime.default_provider || providers[0].provider;
  syncModelInput();
  renderRuntimeStatus();
}

function syncModelInput() {
  const provider = providerByName(els.providerSelect.value);
  els.modelInput.value = provider && provider.model ? provider.model : "";
  renderRuntimeStatus();
}

function renderRuntimeStatus() {
  const provider = providerByName(els.providerSelect.value);
  const model = els.modelInput.value.trim() || (provider && provider.model) || "";
  const ready = Boolean(provider && provider.configured && model);
  els.runtimeStatus.textContent = ready
    ? "陪伴服务已连接"
    : "后台模型未配置";
  els.modelHint.textContent = ready
    ? "请求会从本地服务端转发，浏览器不保存 API key。"
    : "请在 .env 中配置对应 provider 的 API key 和 model。";
  renderStatePills();
}

function renderPersonas() {
  els.personaSelect.innerHTML = "";
  for (const persona of state.personas) {
    const option = document.createElement("option");
    option.value = persona.id;
    option.textContent = persona.name;
    els.personaSelect.appendChild(option);
  }
  if (!state.activeId && state.personas[0]) {
    state.activeId = state.personas[0].id;
  }
  els.personaSelect.value = state.activeId;
  renderInspector();
}

function activePersona() {
  return state.personas.find((persona) => persona.id === state.activeId) || null;
}

function renderInspector(hits = []) {
  const persona = activePersona();
  els.modeValue.textContent = persona ? (persona.memoryAware ? "记忆陪伴" : "风格陪伴") : "未加载";
  els.userIdValue.textContent = persona ? persona.userId : "-";
  els.sampleCountValue.textContent = persona ? String(persona.samples.length) : "0";
  els.memoryCountValue.textContent = `${state.memoryRows.length} 条`;
  const title = persona ? persona.name : "智能陪伴";
  els.appTitle.textContent = title;
  els.brandMark.textContent = persona ? title.trim().slice(0, 1).toUpperCase() : "S";
  document.title = title;
  els.conversationTitle.textContent = persona ? persona.name : "加载 skill 后开始对话";
  els.conversationSub.textContent = persona
    ? `已学习 ${persona.samples.length} 条样本表达`
    : "在后台设置加载 .skill 或 .chat-memory.skill 文件";
  els.typingStatus.hidden = true;
  els.styleTokens.innerHTML = "";
  if (!persona) {
    addToken("No persona", "amber");
  } else {
    addToken(persona.name, "teal");
    addToken(persona.memoryAware ? "recall" : "style");
    for (const phrase of persona.phrases.slice(0, 10)) {
      addToken(phrase);
    }
  }
  renderHits(hits);
  renderStatePills();
}

function renderStatePills() {
  const persona = activePersona();
  const provider = providerByName(els.providerSelect.value);
  const cloudMemory = state.runtime.memory || {};
  els.statePills.innerHTML = "";
  addPill(persona ? "风格已加载" : "未加载风格", persona ? "ok" : "warn");
  addPill(cloudMemory.configured ? "云记忆已连接" : `${state.memoryRows.length} 条本地记忆`, cloudMemory.configured || state.memoryRows.length ? "ok" : "");
  addPill(provider && provider.configured ? "服务已连接" : "服务未配置", provider && provider.configured ? "ok" : "warn");
}

function addPill(text, tone = "") {
  const pill = document.createElement("span");
  pill.className = `pill ${tone}`.trim();
  pill.textContent = text;
  els.statePills.appendChild(pill);
}

function addToken(text, tone = "") {
  const token = document.createElement("span");
  token.className = `token ${tone}`.trim();
  token.textContent = text;
  els.styleTokens.appendChild(token);
}

function renderHits(hits) {
  els.memoryHits.innerHTML = "";
  if (!hits.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无命中";
    els.memoryHits.appendChild(empty);
    return;
  }
  for (const hit of hits.slice(0, 6)) {
    const item = document.createElement("div");
    item.className = "hit";
    item.textContent = hit.content || JSON.stringify(hit);
    els.memoryHits.appendChild(item);
  }
}

function appendMessage(role, text, options = {}) {
  const { record = true, pending = false } = options;
  const node = els.messageTemplate.content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  if (pending) node.classList.add("pending");
  node.querySelector(".bubble").textContent = text;
  els.chatLog.appendChild(node);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
  if (record) {
    state.transcript.push({ role, text, timestamp: new Date().toISOString() });
  }
  return node;
}

function updateMessage(node, text, options = {}) {
  node.querySelector(".bubble").textContent = text;
  node.classList.toggle("pending", Boolean(options.pending));
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function keywordSet(input) {
  return [...new Set(input.split(/[^\p{L}\p{N}]+/u).map((item) => item.trim()).filter((item) => item.length >= 2))];
}

function searchMemory(input, persona) {
  if (!state.memoryRows.length) return [];
  const keys = keywordSet(input);
  return state.memoryRows.filter((row) => {
    const text = `${row.content || ""} ${JSON.stringify(row.metadata || {})}`;
    const sameUser = !persona || !row.metadata || !row.metadata.userID || row.metadata.userID === persona.userId;
    return sameUser && keys.some((key) => text.includes(key));
  });
}

async function readTextFile(file) {
  return file.text();
}

async function loadSkillFiles(files) {
  const loaded = [];
  for (const file of files) {
    const text = await readTextFile(file);
    loaded.push(parseSkill(text, file.name));
  }
  state.personas = loaded;
  state.activeId = loaded[0] ? loaded[0].id : "";
  renderPersonas();
  appendMessage("system", `已加载 ${loaded.length} 个 skill 文件。`);
}

async function loadMemoryFile(file) {
  const text = await readTextFile(file);
  const rows = [];
  const errors = [];
  text.split(/\n+/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      rows.push(JSON.parse(trimmed));
    } catch (error) {
      errors.push(index + 1);
    }
  });
  state.memoryRows = rows;
  renderInspector();
  if (errors.length) {
    appendMessage("system", `已加载 ${rows.length} 条记忆，跳过 ${errors.length} 行无法解析的 JSONL。`);
  } else {
    appendMessage("system", `已加载 ${rows.length} 条记忆。`);
  }
}

function loadDemo() {
  state.personas = [parseSkill(demoSkill, "Participant B.chat-memory.skill")];
  state.activeId = state.personas[0].id;
  state.memoryRows = demoMemory;
  state.transcript = [];
  els.chatLog.innerHTML = "";
  renderPersonas();
  appendMessage("system", "Demo 已加载，可以开始聊天。");
}

function exportTranscript() {
  const blob = new Blob([JSON.stringify(state.transcript, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "chat-transcript.json";
  link.click();
  URL.revokeObjectURL(url);
}

function recentHistory() {
  return state.transcript
    .filter((item) => item.role === "user" || item.role === "assistant")
    .slice(-12)
    .map((item) => ({ role: item.role, text: item.text }));
}

async function sendMessage(input) {
  const persona = activePersona();
  if (!persona) {
    appendMessage("system", "请先加载并选择一个 skill。");
    return;
  }
  const hits = searchMemory(input, persona);
  const history = recentHistory();
  renderInspector(hits);
  appendMessage("user", input);
  els.typingStatus.hidden = false;
  const pending = appendMessage("assistant", "对方正在输入中...", { record: false, pending: true });
  state.busy = true;
  setComposerEnabled(false);
  try {
    const response = await fetch("./api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: els.providerSelect.value,
        model: els.modelInput.value.trim(),
        message: input,
        skill: persona.raw,
        persona: { name: persona.name, userId: persona.userId },
        memory_hits: hits.slice(0, 8),
        history
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    const text = (payload.text || "").trim() || "我这边没生成出有效回复。";
    if (Array.isArray(payload.memory_hits)) {
      renderInspector(payload.memory_hits);
    }
    updateMessage(pending, text);
    state.transcript.push({
      role: "assistant",
      text,
      timestamp: new Date().toISOString(),
      provider: payload.provider,
      model: payload.model
    });
  } catch (error) {
    updateMessage(pending, `回复失败：${error.message}`);
    pending.classList.remove("assistant");
    pending.classList.add("system");
  } finally {
    state.busy = false;
    els.typingStatus.hidden = true;
    setComposerEnabled(true);
    els.messageInput.focus();
  }
}

function setComposerEnabled(enabled) {
  els.messageInput.disabled = !enabled;
  els.composer.querySelector("button[type='submit']").disabled = !enabled;
}

async function loadRuntime() {
  try {
    const response = await fetch("./api/runtime", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.runtime = await response.json();
  } catch (error) {
    state.runtime = { default_provider: "openai", providers: [] };
    els.runtimeStatus.textContent = `无法读取模型服务：${error.message}`;
  }
  renderProviders();
}

els.skillFiles.addEventListener("change", (event) => loadSkillFiles(event.target.files));
els.memoryFile.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) loadMemoryFile(file);
});
els.providerSelect.addEventListener("change", syncModelInput);
els.modelInput.addEventListener("input", renderRuntimeStatus);
els.personaSelect.addEventListener("change", (event) => {
  state.activeId = event.target.value;
  renderInspector();
});
els.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});
els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy) return;
  const input = els.messageInput.value.trim();
  if (!input) return;
  els.messageInput.value = "";
  sendMessage(input);
});
els.clearChat.addEventListener("click", () => {
  state.transcript = [];
  els.chatLog.innerHTML = "";
  renderInspector();
  appendMessage("system", "对话已清空。");
});
els.exportChat.addEventListener("click", exportTranscript);
els.loadDemo.addEventListener("click", loadDemo);

renderPersonas();
renderHits([]);
loadRuntime();
appendMessage("system", "在后台设置加载 skill 后即可开始聊天。");
