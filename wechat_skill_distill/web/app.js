const state = {
  personas: [],
  activeId: "",
  memoryRows: [],
  transcript: [],
  runtime: { default_provider: "openai", providers: [] },
  lastRecall: null,
  busy: false
};

const els = {
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
  companionStatus: document.getElementById("companionStatus"),
  chatLog: document.getElementById("chatLog"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
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

function parseSkill(text, fileName = "skill", stableId = "") {
  const titleMatch = text.match(/^#\s+(.+?)\s+(Chat\s+)?Skill\s*$/m);
  const userMatch = text.match(/userID=([^\s，。`]+)/);
  const commonLine = text.match(/常见表达：([^\n]+)/);
  const samples = [...text.matchAll(/```text\n([\s\S]*?)\n```/g)].map((match) => match[1].trim()).filter(Boolean);
  const phrases = commonLine ? commonLine[1].replace(/[。.;；]\s*$/, "").split(/[、,，]/).map((item) => item.trim()).filter(Boolean) : [];
  const name = titleMatch ? titleMatch[1].trim() : fileName.replace(/\.(chat-memory\.)?skill$/i, "");
  const id = stableId || `${userMatch ? userMatch[1] : name}-${Math.random().toString(16).slice(2)}`;
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

function renderInspector() {
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
    : "请在启动服务时通过 --skill 指定陪伴对象";
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
  renderCompanionStatus();
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

function renderCompanionStatus() {
  const persona = activePersona();
  const cloudMemory = state.runtime.memory || {};
  els.companionStatus.innerHTML = "";
  addStatus("陪伴对象", persona ? persona.name : "未加载");
  addStatus("风格来源", persona ? "服务端启动加载" : "等待服务端配置");
  addStatus("云记忆", cloudMemory.configured ? "已接入" : "未接入");
  addStatus("本地素材", state.memoryRows.length ? `${state.memoryRows.length} 条` : "未加载");
  addStatus("本轮记忆", state.lastRecall ? "已参考相关上下文" : "等待对话");
}

function addStatus(label, value) {
  const row = document.createElement("div");
  row.className = "status-row";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  row.append(labelNode, valueNode);
  els.companionStatus.appendChild(row);
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
    appendMessage("system", "服务未加载陪伴对象，请用 --skill 启动。");
    return;
  }
  const hits = searchMemory(input, persona);
  const history = recentHistory();
  renderInspector();
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
    state.lastRecall = payload.memory && payload.memory.server_hits ? { serverHits: payload.memory.server_hits } : null;
    renderInspector();
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

async function loadServerSkills() {
  try {
    const response = await fetch("./api/skills", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const skills = Array.isArray(payload.skills) ? payload.skills : [];
    state.personas = skills.map((skill) => parseSkill(skill.text || "", skill.file_name || "skill", skill.id || ""));
    state.activeId = state.personas[0] ? state.personas[0].id : "";
    renderPersonas();
    if (state.personas.length) {
      appendMessage("system", `已连接 ${state.personas[0].name}。`);
    } else {
      appendMessage("system", "服务启动时未指定陪伴对象。请使用 --skill <file> 重新启动。");
    }
  } catch (error) {
    renderPersonas();
    appendMessage("system", `无法读取服务端 skill：${error.message}`);
  }
}

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

renderPersonas();
loadRuntime().then(loadServerSkills);
appendMessage("system", "正在连接陪伴对象。");
