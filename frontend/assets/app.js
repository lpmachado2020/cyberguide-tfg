const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const resetButton = document.getElementById("resetButton");
const chatStream = document.getElementById("chatStream");
const chatTitle = document.getElementById("chatTitle");
const chatList = document.getElementById("chatList");
const chatSearchInput = document.getElementById("chatSearchInput");
const sourcesList = document.getElementById("sourcesList");
const tracePanel = document.getElementById("tracePanel");
const statusBadge = document.getElementById("statusBadge");
const pdfInput = document.getElementById("pdfInput");
const imageInput = document.getElementById("imageInput");
const helperText = document.getElementById("helperText");
const modePill = document.getElementById("modePill");
const processingPill = document.getElementById("processingPill");
const inspectorTabs = document.querySelectorAll(".inspector-tab");
const processView = document.getElementById("processView");
const sourcesView = document.getElementById("sourcesView");

const userMessageTemplate = document.getElementById("userMessageTemplate");
const assistantMessageTemplate = document.getElementById("assistantMessageTemplate");
const sourceCardTemplate = document.getElementById("sourceCardTemplate");
const thinkingMessageTemplate = document.getElementById("thinkingMessageTemplate");

const promptChips = document.querySelectorAll(".prompt-chip[data-prompt]");

const DEFAULT_HELPER_TEXT = "Current corpus: INCIBE policy documents in local Chroma.";
const PDF_HELPER_PREFIX = "Current mode: conversation grounded in uploaded PDF";
const IMAGE_HELPER_PREFIX = "Current mode: conversation grounded in OCR text from uploaded image";
const STORAGE_KEY = "cyberguideChatHistory";
const ACTIVE_CHAT_KEY = "cyberguideActiveChatId";

const INTRO_MESSAGE = "Ask a question, upload a PDF, or upload an image to start a grounded conversation.";

let activeChat = null;
let activeMode = "corpus";
let activeDocumentTitle = "";
let thinkingState = null;

initializeApp();

function initializeApp() {
  bindPromptChips();
  bindInspectorTabs();
  setupComposerShortcuts();
  bindSidebarSearch();
  autosizeComposer();

  const chats = loadChats();
  if (!chats.length) {
    activeChat = createChatRecord();
    persistChats([activeChat]);
  } else {
    activeChat = getInitialActiveChat(chats);
  }

  loadChat(activeChat.id);
  setProcessingState("Idle", false);
}

function bindPromptChips() {
  for (const chip of promptChips) {
    chip.addEventListener("click", () => {
      messageInput.value = chip.dataset.prompt || "";
      autosizeComposer();
      messageInput.focus();
    });
  }
}

function bindSidebarSearch() {
  chatSearchInput.addEventListener("input", () => {
    renderChatList(chatSearchInput.value.trim().toLowerCase());
  });
}

function bindInspectorTabs() {
  for (const tab of inspectorTabs) {
    tab.addEventListener("click", () => {
      activateInspectorTab(tab.dataset.tab || "process");
    });
  }
}

function setupComposerShortcuts() {
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  messageInput.addEventListener("input", () => {
    autosizeComposer();
  });

  resetButton.addEventListener("click", () => {
    const chat = createChatRecord();
    const chats = [chat, ...loadChats()];
    persistChats(deduplicateChats(chats));
    loadChat(chat.id);
    messageInput.focus();
  });

  chatForm.addEventListener("submit", handleSubmit);
}

async function handleSubmit(event) {
  event.preventDefault();
  const question = messageInput.value.trim();
  if (!question) return;

  const selectedFile = pdfInput.files?.[0] || null;
  const selectedImage = imageInput.files?.[0] || null;
  if (selectedFile && selectedImage) {
    appendMessage("assistant", "Adjunta solo un archivo por consulta: o PDF o imagen.");
    statusBadge.textContent = "Select one file";
    return;
  }

  ensureActiveChat();
  appendMessage("user", question);

  const useImageMode = Boolean(selectedImage) || (!selectedFile && activeMode === "image");
  const usePdfMode = Boolean(selectedFile) || (!selectedImage && !selectedFile && activeMode === "pdf");

  messageInput.value = "";
  autosizeComposer();
  sendButton.disabled = true;

  const processingLabel = selectedImage
    ? "Reading image"
    : selectedFile
      ? "Reading PDF"
      : useImageMode
        ? "Thinking over image"
        : usePdfMode
          ? "Thinking over PDF"
          : "Thinking";

  statusBadge.textContent = processingLabel;
  setProcessingState(processingLabel, true);
  startThinking(useImageMode ? "image" : usePdfMode ? "pdf" : "corpus");

  try {
    const response = useImageMode
      ? await submitImageQuestion(question, selectedImage)
      : usePdfMode
        ? await submitPdfQuestion(question, selectedFile)
        : await submitCorpusQuestion(question);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    activeChat.sessionId = payload.session_id || activeChat.sessionId;
    activeMode = payload.mode || "corpus";
    activeDocumentTitle = payload.document_title || "";

    appendMessage("assistant", payload.answer);
    renderSources(payload.sources || []);
    renderTrace(payload.trace || null);

    activeChat.mode = activeMode;
    activeChat.documentTitle = activeDocumentTitle;
    activeChat.trace = payload.trace || null;
    activeChat.sources = payload.sources || [];
    activeChat.updatedAt = Date.now();
    saveActiveChat();

    stopThinking();
    statusBadge.textContent =
      payload.mode === "image"
        ? "OCR answer ready"
        : payload.mode === "pdf"
          ? "PDF answer ready"
          : "Answer ready";
    setProcessingState(statusBadge.textContent, false);
    syncHelperText();
    syncModeUI();
    activateInspectorTab("process");
    scrollToLatestMessage();
  } catch (error) {
    stopThinking();
    appendMessage(
      "assistant",
      "No he podido consultar el backend local. Revisa que la API de CyberGuide esté levantada."
    );
    renderSources([]);
    renderTrace(null);
    statusBadge.textContent = "API error";
    setProcessingState("Error", false);
    console.error(error);
  } finally {
    pdfInput.value = "";
    imageInput.value = "";
    sendButton.disabled = false;
    scrollToLatestMessage();
  }
}

async function submitCorpusQuestion(question) {
  return fetch("/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: question,
      top_k: 4,
      session_id: activeChat.sessionId,
    }),
  });
}

async function submitPdfQuestion(question, file) {
  const formData = new FormData();
  formData.append("message", question);
  formData.append("session_id", activeChat.sessionId);

  if (file) {
    formData.append("file", file);
  }

  return fetch("/query_pdf", {
    method: "POST",
    body: formData,
  });
}

async function submitImageQuestion(question, file) {
  const formData = new FormData();
  formData.append("message", question);
  formData.append("session_id", activeChat.sessionId);

  if (file) {
    formData.append("file", file);
  }

  return fetch("/query_image", {
    method: "POST",
    body: formData,
  });
}

function loadChat(chatId) {
  const chats = loadChats();
  const match = chats.find((chat) => chat.id === chatId) || chats[0] || createChatRecord();
  activeChat = match;
  activeMode = match.mode || "corpus";
  activeDocumentTitle = match.documentTitle || "";
  localStorage.setItem(ACTIVE_CHAT_KEY, activeChat.id);

  chatTitle.textContent = activeChat.title || "New chat";
  renderMessages(activeChat.messages || []);
  renderSources(activeChat.sources || []);
  renderTrace(activeChat.trace || null);
  syncHelperText();
  syncModeUI();
  renderChatList(chatSearchInput.value.trim().toLowerCase());
  statusBadge.textContent = "Ready";
  setProcessingState("Idle", false);
}

function renderMessages(messages) {
  chatStream.innerHTML = "";

  if (!messages.length) {
    chatStream.innerHTML = `
      <article class="message assistant intro">
        <p>${INTRO_MESSAGE}</p>
      </article>
    `;
    return;
  }

  for (const message of messages) {
    appendMessage(message.role, message.content, { persist: false });
  }

  scrollToLatestMessage();
}

function appendMessage(role, content, options = { persist: true }) {
  const template =
    role === "user" ? userMessageTemplate.content.cloneNode(true) : assistantMessageTemplate.content.cloneNode(true);
  const paragraph = template.querySelector("p");
  paragraph.textContent = content;
  chatStream.appendChild(template);

  if (options.persist) {
    ensureActiveChat();
    activeChat.messages.push({ role, content });
    activeChat.updatedAt = Date.now();
    if (role === "user" && isUntitledChat(activeChat.title)) {
      activeChat.title = buildChatTitle(content);
      chatTitle.textContent = activeChat.title;
    }
    saveActiveChat();
  }

  scrollToLatestMessage();
}

function renderSources(sources) {
  sourcesList.innerHTML = "";

  if (!sources.length) {
    sourcesList.classList.add("empty");
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No retrieved sources yet.";
    sourcesList.appendChild(empty);
    return;
  }

  sourcesList.classList.remove("empty");

  for (const source of sources) {
    const node = sourceCardTemplate.content.cloneNode(true);
    const title = node.querySelector(".source-title");
    const distance = node.querySelector(".source-distance");
    const excerpt = node.querySelector(".source-excerpt");
    const link = node.querySelector(".source-link");

    title.textContent = prettifyTitle(source.metadata?.title || "Untitled source");
    distance.textContent =
      typeof source.distance === "number" ? `distance ${source.distance.toFixed(3)}` : "distance n/a";
    excerpt.textContent = source.text || "";

    const url = source.metadata?.source_url || "";
    if (url) {
      link.href = url;
      link.textContent = "Open source";
    } else {
      link.textContent =
        source.metadata?.source_kind === "ocr-image"
          ? "Temporary OCR image"
          : "Temporary uploaded document";
      link.removeAttribute("href");
    }

    sourcesList.appendChild(node);
  }
}

function renderTrace(trace) {
  tracePanel.innerHTML = "";

  if (!trace) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "The processing steps for the latest answer will appear here.";
    tracePanel.appendChild(empty);
    return;
  }

  const summary = document.createElement("p");
  summary.className = "trace-summary";
  summary.textContent = trace.summary || "Trace not available.";
  tracePanel.appendChild(summary);

  const meta = document.createElement("div");
  meta.className = "trace-meta";
  meta.appendChild(buildTracePill(`history ${trace.history_turns ?? 0}`));
  meta.appendChild(buildTracePill(`retrieved ${trace.retrieved_candidates ?? 0}`));
  meta.appendChild(buildTracePill(`kept ${trace.curated_candidates ?? 0}`));
  if (trace.safety_mode) {
    meta.appendChild(buildTracePill("cautious safety mode"));
  }
  if (trace.active_document) {
    meta.appendChild(buildTracePill(trace.active_document));
  }
  tracePanel.appendChild(meta);

  const steps = document.createElement("div");
  steps.className = "trace-steps";

  for (const step of trace.steps || []) {
    const item = document.createElement("article");
    item.className = "trace-step";

    const title = document.createElement("h3");
    title.textContent = step.title || "Step";
    item.appendChild(title);

    const detail = document.createElement("p");
    detail.textContent = step.detail || "";
    item.appendChild(detail);

    steps.appendChild(item);
  }

  tracePanel.appendChild(steps);
}

function renderChatList(filterText = "") {
  chatList.innerHTML = "";
  const chats = loadChats()
    .filter((chat) => chat.title.toLowerCase().includes(filterText))
    .sort((a, b) => b.updatedAt - a.updatedAt);

  if (!chats.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No chats found.";
    chatList.appendChild(empty);
    return;
  }

  for (const chat of chats) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-list-item";
    if (chat.id === activeChat.id) {
      button.classList.add("chat-list-item-active");
    }

    const title = document.createElement("span");
    title.className = "chat-list-title";
    title.textContent = chat.title || "New chat";

    const meta = document.createElement("span");
    meta.className = "chat-list-meta";
    meta.textContent = formatRelativeDate(chat.updatedAt);

    button.appendChild(title);
    button.appendChild(meta);
    button.addEventListener("click", () => loadChat(chat.id));
    chatList.appendChild(button);
  }
}

function createChatRecord() {
  const id = crypto.randomUUID();
  return {
    id,
    sessionId: id,
    title: "New chat",
    messages: [],
    mode: "corpus",
    documentTitle: "",
    trace: null,
    sources: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

function ensureActiveChat() {
  if (activeChat) return;
  const chats = loadChats();
  activeChat = chats[0] || createChatRecord();
}

function loadChats() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

function persistChats(chats) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
}

function saveActiveChat() {
  const chats = loadChats();
  const remaining = chats.filter((chat) => chat.id !== activeChat.id);
  persistChats(deduplicateChats([activeChat, ...remaining]));
  localStorage.setItem(ACTIVE_CHAT_KEY, activeChat.id);
  renderChatList(chatSearchInput.value.trim().toLowerCase());
}

function deduplicateChats(chats) {
  const seen = new Set();
  return chats.filter((chat) => {
    if (seen.has(chat.id)) return false;
    seen.add(chat.id);
    return true;
  });
}

function getInitialActiveChat(chats) {
  const storedId = localStorage.getItem(ACTIVE_CHAT_KEY);
  return chats.find((chat) => chat.id === storedId) || chats[0];
}

function buildChatTitle(content) {
  return content.trim().slice(0, 48) + (content.trim().length > 48 ? "..." : "");
}

function isUntitledChat(title) {
  return !title || title === "New chat";
}

function setupComposerShortcuts() {
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  messageInput.addEventListener("input", () => {
    autosizeComposer();
  });
}

function autosizeComposer() {
  messageInput.style.height = "auto";
  const nextHeight = Math.min(messageInput.scrollHeight, 180);
  messageInput.style.height = `${Math.max(nextHeight, 28)}px`;
}

function activateInspectorTab(tabName) {
  const isProcess = tabName === "process";
  for (const tab of inspectorTabs) {
    tab.classList.toggle("inspector-tab-active", tab.dataset.tab === tabName);
  }
  processView.classList.toggle("inspector-view-active", isProcess);
  sourcesView.classList.toggle("inspector-view-active", !isProcess);
}

function syncModeUI() {
  const labels = {
    corpus: "Corpus mode",
    pdf: "PDF mode",
    image: "OCR image mode",
  };
  modePill.textContent = labels[activeMode] || "Corpus mode";
  modePill.classList.add("mode-pill-active");
}

function syncHelperText() {
  if (activeMode === "image" && activeDocumentTitle) {
    helperText.textContent = `${IMAGE_HELPER_PREFIX}: ${activeDocumentTitle}.`;
    return;
  }

  if (activeMode === "pdf" && activeDocumentTitle) {
    helperText.textContent = `${PDF_HELPER_PREFIX}: ${activeDocumentTitle}.`;
    return;
  }

  helperText.textContent = DEFAULT_HELPER_TEXT;
}

function setProcessingState(label, active) {
  processingPill.textContent = label;
  processingPill.classList.toggle("mode-pill-active", active);
}

function startThinking(mode) {
  stopThinking();

  const template = thinkingMessageTemplate.content.cloneNode(true);
  const thinkingNode = template.querySelector(".thinking");
  const thinkingStep = template.querySelector(".thinking-step");
  const phases = getThinkingPhases(mode);
  let index = 0;

  thinkingStep.textContent = phases[index];
  chatStream.appendChild(template);
  scrollToLatestMessage();

  const intervalId = window.setInterval(() => {
    if (!thinkingNode?.isConnected) return;
    index = (index + 1) % phases.length;
    thinkingStep.textContent = phases[index];
    scrollToLatestMessage();
  }, 1400);

  thinkingState = {
    node: thinkingNode,
    intervalId,
  };
}

function stopThinking() {
  if (!thinkingState) return;
  window.clearInterval(thinkingState.intervalId);
  thinkingState.node?.remove();
  thinkingState = null;
}

function getThinkingPhases(mode) {
  if (mode === "pdf") {
    return [
      "Reading the uploaded PDF.",
      "Selecting the most relevant grounded fragments.",
      "Drafting a cautious answer from the retrieved evidence.",
    ];
  }

  if (mode === "image") {
    return [
      "Running OCR on the uploaded image.",
      "Checking whether the screenshot looks sensitive.",
      "Grounding the answer in the extracted text and active policy.",
    ];
  }

  return [
    "Searching the local INCIBE corpus.",
    "Keeping the most relevant chunks for this question.",
    "Drafting a concise grounded answer.",
  ];
}

function scrollToLatestMessage() {
  const lastMessage = chatStream.lastElementChild;
  if (!lastMessage) return;
  lastMessage.scrollIntoView({ behavior: "smooth", block: "end" });
}

function prettifyTitle(value) {
  return value
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function buildTracePill(text) {
  const pill = document.createElement("span");
  pill.className = "trace-pill";
  pill.textContent = text;
  return pill;
}

function formatRelativeDate(timestamp) {
  const deltaMinutes = Math.round((Date.now() - timestamp) / 60000);
  if (deltaMinutes < 1) return "now";
  if (deltaMinutes < 60) return `${deltaMinutes}m`;
  const deltaHours = Math.round(deltaMinutes / 60);
  if (deltaHours < 24) return `${deltaHours}h`;
  const deltaDays = Math.round(deltaHours / 24);
  return `${deltaDays}d`;
}
