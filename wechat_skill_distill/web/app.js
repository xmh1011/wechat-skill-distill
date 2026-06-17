const state = {
  personas: [],
  activeId: "",
  transcriptsByPersona: {},
  runtime: { default_provider: "openai", providers: [] },
  lastRecallByPersona: {},
  busy: false
};

const els = {
  providerSelect: document.getElementById("providerSelect"),
  modelInput: document.getElementById("modelInput"),
  modelHint: document.getElementById("modelHint"),
  personaSelect: document.getElementById("personaSelect"),
  modeValue: document.getElementById("modeValue"),
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

function normalizePersona(skill) {
  const name = String(skill.name || "未命名对象").trim();
  const id = String(skill.id || `persona-${Math.random().toString(16).slice(2)}`);
  return {
    id,
    name,
    memoryAware: Boolean(skill.memoryAware),
    sampleCount: Number.isFinite(Number(skill.sampleCount)) ? Number(skill.sampleCount) : 0
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
  els.providerSelect.disabled = true;
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
    : "服务未配置";
  els.modelHint.textContent = ready
    ? "模型协议、模型和 API key 由本地服务端环境变量决定；记忆由本地服务端按配置检索。"
    : "请在 .env 中配置服务端 provider、API key 和 model；记忆由本地服务端按配置检索。";
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

function activeTranscriptKey() {
  return state.activeId || "__pending__";
}

function transcriptForPersona(personaId) {
  const key = personaId || "__pending__";
  if (!state.transcriptsByPersona[key]) {
    state.transcriptsByPersona[key] = [];
  }
  return state.transcriptsByPersona[key];
}

function activeTranscript() {
  return transcriptForPersona(activeTranscriptKey());
}

function recallForPersona(personaId) {
  return state.lastRecallByPersona[personaId || "__pending__"] || null;
}

function activeRecall() {
  return recallForPersona(activeTranscriptKey());
}

function setRecallForPersona(personaId, value) {
  const key = personaId || "__pending__";
  if (value) {
    state.lastRecallByPersona[key] = value;
  } else {
    delete state.lastRecallByPersona[key];
  }
}

function setActiveRecall(value) {
  setRecallForPersona(activeTranscriptKey(), value);
}

function renderInspector() {
  const persona = activePersona();
  const memory = state.runtime.memory || {};
  els.modeValue.textContent = persona ? (persona.memoryAware ? "记忆陪伴" : "风格陪伴") : "未加载";
  els.sampleCountValue.textContent = persona ? String(persona.sampleCount) : "0";
  els.memoryCountValue.textContent = memory.configured ? memory.backend : "未接入";
  const title = persona ? persona.name : "智能陪伴";
  els.appTitle.textContent = title;
  els.brandMark.textContent = persona ? title.trim().slice(0, 1).toUpperCase() : "伴";
  document.title = title;
  els.conversationTitle.textContent = persona ? persona.name : "加载 skill 后开始对话";
  els.conversationSub.textContent = persona
    ? `已配置 ${persona.sampleCount} 条风格样本`
    : "请在启动服务时通过 --skill 指定陪伴对象";
  els.typingStatus.hidden = true;
  els.styleTokens.innerHTML = "";
  if (!persona) {
    addToken("未加载对象", "amber");
  } else {
    addToken(persona.name, "teal");
    addToken(persona.memoryAware ? "记忆陪伴" : "风格陪伴");
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
  addPill(cloudMemory.configured ? "记忆已连接" : "记忆未接入", cloudMemory.configured ? "ok" : "");
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
  addStatus("记忆来源", cloudMemory.configured ? cloudMemory.backend : "未接入");
  addStatus("本轮记忆", activeRecall() ? "已参考相关上下文" : "等待对话");
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
    activeTranscript().push({ role, text, timestamp: new Date().toISOString() });
  }
  return node;
}

function updateMessage(node, text, options = {}) {
  node.querySelector(".bubble").textContent = text;
  node.classList.toggle("pending", Boolean(options.pending));
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function exportTranscript() {
  const persona = activePersona();
  const payload = {
    persona: persona ? { id: persona.id, name: persona.name } : null,
    transcript: activeTranscript()
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "chat-transcript.json";
  link.click();
  URL.revokeObjectURL(url);
}

function renderTranscript() {
  els.chatLog.innerHTML = "";
  for (const item of activeTranscript()) {
    appendMessage(item.role, item.text, { record: false });
  }
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function switchPersona(personaId, options = {}) {
  const { announce = false } = options;
  state.activeId = personaId;
  els.personaSelect.value = state.activeId;
  renderInspector();
  renderTranscript();
  const persona = activePersona();
  if (announce && persona && activeTranscript().length === 0) {
    appendMessage("system", `已连接 ${persona.name}。`, { record: false });
  }
}

function recentHistory() {
  return activeTranscript()
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
  const personaId = persona.id;
  const history = recentHistory();
  setRecallForPersona(personaId, null);
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
        message: input,
        skill_id: personaId,
        history
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    const text = (payload.text || "").trim() || "我这边没生成出有效回复。";
    setRecallForPersona(personaId, payload.memory && payload.memory.server_hits ? { serverHits: payload.memory.server_hits } : null);
    renderInspector();
    updateMessage(pending, text);
    transcriptForPersona(personaId).push({
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
    state.personas = skills.map((skill) => normalizePersona(skill));
    state.activeId = state.personas[0] ? state.personas[0].id : "";
    renderPersonas();
    if (state.personas.length) {
      switchPersona(state.personas[0].id, { announce: true });
    } else {
      renderTranscript();
      appendMessage("system", "服务启动时未指定陪伴对象。请使用 --skill <file> 重新启动。", { record: false });
    }
  } catch (error) {
    renderPersonas();
    renderTranscript();
    appendMessage("system", `无法读取服务端 skill：${error.message}`, { record: false });
  }
}

els.providerSelect.addEventListener("change", syncModelInput);
els.modelInput.addEventListener("input", renderRuntimeStatus);
els.personaSelect.addEventListener("change", (event) => {
  switchPersona(event.target.value, { announce: true });
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
  state.transcriptsByPersona[activeTranscriptKey()] = [];
  setActiveRecall(null);
  renderInspector();
  renderTranscript();
  appendMessage("system", "对话已清空。", { record: false });
});
els.exportChat.addEventListener("click", exportTranscript);

renderPersonas();
loadRuntime().then(loadServerSkills);
appendMessage("system", "正在连接陪伴对象。", { record: false });
