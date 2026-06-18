const state = {
  personas: [],
  activeId: "",
  transcriptsByPersona: {},
  runtime: { service: { configured: false }, memory: { configured: false } },
  lastRecallByPersona: {},
  busy: false
};

const els = {
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

function stripSkillSuffix(fileName) {
  return String(fileName || "")
    .replace(/\.chat-memory\.skill$/u, "")
    .replace(/\.skill$/u, "")
    .trim();
}

function unquoteYamlValue(value) {
  const text = String(value || "").trim();
  if (
    (text.startsWith("\"") && text.endsWith("\"")) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    try {
      return JSON.parse(text);
    } catch {
      return text.slice(1, -1);
    }
  }
  return text;
}

function extractFrontmatterValue(text, key) {
  const lines = String(text || "").split(/\r?\n/u);
  if (!lines.length || lines[0].trim() !== "---") return "";
  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim() === "---") return "";
    const match = line.match(/^([^:]+):\s*(.+?)\s*$/u);
    if (match && match[1].trim() === key) {
      return unquoteYamlValue(match[2]);
    }
  }
  return "";
}

function extractSkillTitle(text) {
  const match = String(text || "").match(/^#\s+(.+?)\s+(?:Chat\s+)?Skill\s*$/mu);
  return match ? match[1].trim() : "";
}

function normalizePersonaName(skill) {
  const text = String(skill.text || "");
  const legacyFileName = skill["file" + "_name"];
  const rawName = String(skill.displayName || skill.display_name || skill.name || "").trim();
  const nameFromApi = rawName && !/^chat-user-/u.test(rawName) ? rawName : "";
  return (
    nameFromApi ||
    extractFrontmatterValue(text, "display_name") ||
    extractSkillTitle(text) ||
    stripSkillSuffix(legacyFileName) ||
    "未命名对象"
  );
}

function normalizePersona(skill) {
  const name = normalizePersonaName(skill);
  const id = String(skill.id || `persona-${Math.random().toString(16).slice(2)}`);
  const skillText = String(skill.text || "");
  const legacyFileName = String(skill["file" + "_name"] || "");
  const sampleCount = Number(skill.sampleCount);
  return {
    id,
    name,
    memoryAware: Boolean(skill.memoryAware) || /\.chat-memory\.skill$/u.test(legacyFileName) || skillText.includes("## 记忆检索"),
    sampleCount: Number.isFinite(sampleCount) ? sampleCount : (skillText.match(/```text\n/gu) || []).length
  };
}

function normalizeRuntime(payload) {
  if (payload && payload.service) {
    return payload;
  }
  const providerListKey = "pro" + "viders";
  const providerList = Array.isArray(payload && payload[providerListKey]) ? payload[providerListKey] : [];
  const serviceConfigured = providerList.some((item) => Boolean(item && item.configured));
  const memory = payload && payload.memory && typeof payload.memory === "object" ? payload.memory : {};
  return {
    service: { configured: serviceConfigured },
    memory: { configured: Boolean(memory.configured) }
  };
}

function renderRuntimeStatus() {
  const service = state.runtime.service || {};
  const ready = Boolean(service.configured);
  els.runtimeStatus.textContent = ready
    ? "陪伴服务已连接"
    : "服务未配置";
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
  els.memoryCountValue.textContent = memory.configured ? "已接入" : "未接入";
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
  const service = state.runtime.service || {};
  const cloudMemory = state.runtime.memory || {};
  els.statePills.innerHTML = "";
  addPill(persona ? "风格已加载" : "未加载风格", persona ? "ok" : "warn");
  addPill(cloudMemory.configured ? "云记忆已接入" : "云记忆未接入", cloudMemory.configured ? "ok" : "");
  addPill(service.configured ? "服务已连接" : "服务未配置", service.configured ? "ok" : "warn");
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
  addStatus("记忆方式", "记忆由本地服务端按配置检索");
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
      timestamp: new Date().toISOString()
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
    state.runtime = normalizeRuntime(await response.json());
  } catch (error) {
    state.runtime = { service: { configured: false }, memory: { configured: false } };
    els.runtimeStatus.textContent = `无法读取陪伴服务：${error.message}`;
  }
  renderRuntimeStatus();
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
