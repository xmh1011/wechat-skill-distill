const state = {
  personas: [],
  activeId: "",
  memoryRows: [],
  transcript: []
};

const els = {
  skillFiles: document.getElementById("skillFiles"),
  memoryFile: document.getElementById("memoryFile"),
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
  runtimeStatus: document.getElementById("runtimeStatus"),
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
  const commonMatch = text.match(/常见表达：(.+?)。/);
  const samples = [...text.matchAll(/```text\n([\s\S]*?)\n```/g)].map((match) => match[1].trim()).filter(Boolean);
  const phrases = commonMatch ? commonMatch[1].split(/[、,，]/).map((item) => item.trim()).filter(Boolean) : [];
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
  els.modeValue.textContent = persona ? (persona.memoryAware ? "Memory-aware" : "Style-only") : "No skill";
  els.userIdValue.textContent = persona ? persona.userId : "-";
  els.sampleCountValue.textContent = persona ? String(persona.samples.length) : "0";
  els.memoryCountValue.textContent = `${state.memoryRows.length} rows`;
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
    empty.textContent = "No hits";
    els.memoryHits.appendChild(empty);
    return;
  }
  for (const hit of hits.slice(0, 5)) {
    const item = document.createElement("div");
    item.className = "hit";
    item.textContent = hit.content || JSON.stringify(hit);
    els.memoryHits.appendChild(item);
  }
}

function appendMessage(role, text) {
  const node = els.messageTemplate.content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  node.querySelector(".bubble").textContent = text;
  els.chatLog.appendChild(node);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
  state.transcript.push({ role, text, timestamp: new Date().toISOString() });
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

function generateReply(input) {
  const persona = activePersona();
  if (!persona) {
    return { text: "先加载一个 skill 文件。", hits: [] };
  }
  const hits = searchMemory(input, persona);
  const sample = persona.samples[Math.floor(Math.random() * Math.max(persona.samples.length, 1))] || "";
  const phrase = persona.phrases[Math.floor(Math.random() * Math.max(persona.phrases.length, 1))] || "可以";
  let text;
  if (hits.length) {
    text = `${phrase}，我看记录里有这个。\n${trimLine(hits[0].content || "")}`;
  } else if (/周末|明天|今晚|约|几点|什么时候/.test(input)) {
    text = sample.includes("明天") ? sample : `${phrase}，先看时间，别把安排说死。`;
  } else if (/怎么|为啥|为什么|咋/.test(input)) {
    text = `${phrase}，我倾向于先把上下文确认一下。`;
  } else {
    text = sample || `${phrase}，这个我先按当前上下文回。`;
  }
  return { text, hits };
}

function trimLine(text) {
  return text.length > 90 ? `${text.slice(0, 90)}...` : text;
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
  appendMessage("system", `Loaded ${loaded.length} skill file${loaded.length === 1 ? "" : "s"}.`);
}

async function loadMemoryFile(file) {
  const text = await readTextFile(file);
  state.memoryRows = text.split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => JSON.parse(line));
  renderInspector();
  appendMessage("system", `Loaded ${state.memoryRows.length} memory rows.`);
}

function loadDemo() {
  state.personas = [parseSkill(demoSkill, "Participant B.chat-memory.skill")];
  state.activeId = state.personas[0].id;
  state.memoryRows = demoMemory;
  state.transcript = [];
  els.chatLog.innerHTML = "";
  renderPersonas();
  appendMessage("assistant", "可以，先把范围卡住，不然越写越散");
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

els.skillFiles.addEventListener("change", (event) => loadSkillFiles(event.target.files));
els.memoryFile.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) loadMemoryFile(file);
});
els.personaSelect.addEventListener("change", (event) => {
  state.activeId = event.target.value;
  renderInspector();
});
els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = els.messageInput.value.trim();
  if (!input) return;
  appendMessage("user", input);
  els.messageInput.value = "";
  const { text, hits } = generateReply(input);
  renderInspector(hits);
  window.setTimeout(() => appendMessage("assistant", text), 180);
});
els.clearChat.addEventListener("click", () => {
  state.transcript = [];
  els.chatLog.innerHTML = "";
  renderInspector();
});
els.exportChat.addEventListener("click", exportTranscript);
els.loadDemo.addEventListener("click", loadDemo);

renderPersonas();
appendMessage("system", "Ready.");
