import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  BranchSet,
  BranchSnapshot,
  Chat,
  ChatMessage,
  ChatMode,
  QueryResponse,
  Source,
  Trace,
} from "@/types/chat";
import { queryCorpus, queryImage, queryPdf } from "@/lib/api";
import { buildTitleSummary } from "@/lib/title";

const STORAGE_KEY = "cyberguideChatHistory";
const ACTIVE_KEY = "cyberguideActiveChatId";

export const MAX_EDITS = 5;
export const MAX_REGEN = 5;

function uid() {
  return (crypto as Crypto & { randomUUID: () => string }).randomUUID();
}

function loadFromStorage(): Chat[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Chat[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persist(chats: Chat[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
}

function newChat(): Chat {
  const id = uid();
  return {
    id,
    sessionId: id,
    title: "Nuevo chat",
    mode: "corpus",
    documentTitle: "",
    messages: [],
    sources: [],
    trace: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    branches: {},
  };
}

const buildTitle = buildTitleSummary;

export type SendStatus = "idle" | "thinking" | "error";

async function callApi(
  mode: ChatMode,
  text: string,
  sessionId: string,
  file: File | null,
): Promise<QueryResponse> {
  if (mode === "image") {
    return queryImage({ message: text, sessionId, file: file && file.type.startsWith("image/") ? file : null });
  }
  if (mode === "pdf") {
    return queryPdf({ message: text, sessionId, file: file && file.type === "application/pdf" ? file : null });
  }
  return queryCorpus({ message: text, sessionId });
}

export function useChats() {
  const [chats, setChats] = useState<Chat[]>(() => {
    const initial = loadFromStorage();
    if (initial.length === 0) {
      const c = newChat();
      persist([c]);
      return [c];
    }
    return initial;
  });

  const [activeId, setActiveId] = useState<string>(() => {
    const stored = localStorage.getItem(ACTIVE_KEY);
    const list = loadFromStorage();
    if (stored && list.some((c) => c.id === stored)) return stored;
    return list[0]?.id ?? chats[0].id;
  });

  const [status, setStatus] = useState<SendStatus>("idle");
  const [thinkingPhase, setThinkingPhase] = useState<string>("");

  useEffect(() => {
    persist(chats);
  }, [chats]);

  useEffect(() => {
    localStorage.setItem(ACTIVE_KEY, activeId);
  }, [activeId]);

  const activeChat = useMemo(
    () => chats.find((c) => c.id === activeId) ?? chats[0],
    [chats, activeId],
  );

  const updateChat = useCallback(
    (id: string, patch: Partial<Chat> | ((c: Chat) => Chat)) => {
      setChats((prev) =>
        prev.map((c) =>
          c.id === id ? (typeof patch === "function" ? patch(c) : { ...c, ...patch }) : c,
        ),
      );
    },
    [],
  );

  const createChat = useCallback(() => {
    // Reutiliza un chat vacío existente si lo hay, en vez de crear duplicados
    let reused: Chat | null = null;
    setChats((prev) => {
      const empty = prev.find((c) => c.messages.length === 0);
      if (empty) {
        reused = empty;
        return prev;
      }
      const c = newChat();
      reused = c;
      return [c, ...prev];
    });
    if (reused) setActiveId(reused.id);
    return reused as unknown as Chat;
  }, []);

  const deleteChat = useCallback(
    (id: string) => {
      setChats((prev) => {
        const next = prev.filter((c) => c.id !== id);
        if (next.length === 0) {
          const c = newChat();
          setActiveId(c.id);
          return [c];
        }
        if (id === activeId) setActiveId(next[0].id);
        return next;
      });
    },
    [activeId],
  );

  const renameChat = useCallback(
    (id: string, title: string) => updateChat(id, { title }),
    [updateChat],
  );

  const toggleStarMessage = useCallback(
    (chatId: string, messageId: string) => {
      setChats((prev) =>
        prev.map((c) => {
          if (c.id !== chatId) return c;
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === messageId
                ? { ...m, starred: !m.starred, starredAt: !m.starred ? Date.now() : undefined }
                : m,
            ),
          };
        }),
      );
    },
    [],
  );

  const togglePinChat = useCallback(
    (id: string) => {
      setChats((prev) =>
        prev.map((c) =>
          c.id === id
            ? { ...c, pinned: !c.pinned, pinnedAt: !c.pinned ? Date.now() : undefined }
            : c,
        ),
      );
    },
    [],
  );

  const selectChat = useCallback((id: string) => setActiveId(id), []);

  const sendMessage = useCallback(
    async (text: string, file: File | null) => {
      const trimmed = text.trim();
      if (!trimmed || !activeChat) return;

      const fileType: "pdf" | "image" | null = file
        ? file.type === "application/pdf"
          ? "pdf"
          : file.type.startsWith("image/")
            ? "image"
            : null
        : null;

      const useImage = fileType === "image" || (!file && activeChat.mode === "image");
      const usePdf = fileType === "pdf" || (!useImage && !file && activeChat.mode === "pdf");
      const mode: ChatMode = useImage ? "image" : usePdf ? "pdf" : "corpus";

      const userMsg: ChatMessage = {
        id: uid(),
        role: "user",
        content: trimmed,
        createdAt: Date.now(),
      };

      const isFirst = activeChat.messages.length === 0;
      updateChat(activeChat.id, (c) => ({
        ...c,
        messages: [...c.messages, userMsg],
        title: isFirst ? buildTitle(trimmed) : c.title,
        updatedAt: Date.now(),
      }));

      setStatus("thinking");
      setThinkingPhase(
        useImage ? "Analizando la imagen…" : usePdf ? "Leyendo el PDF…" : "Buscando en el corpus…",
      );

      try {
        const payload = await callApi(mode, trimmed, activeChat.sessionId, file);
        const nextSources: Source[] = payload.sources ?? [];
        const nextTrace: Trace | null = payload.trace ?? null;
        const assistantMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content: payload.answer || "",
          createdAt: Date.now(),
          trace: nextTrace,
          sources: nextSources,
        };

        const nextMode: ChatMode = (payload.mode as ChatMode) ?? mode;

        updateChat(activeChat.id, (c) => ({
          ...c,
          sessionId: payload.session_id || c.sessionId,
          mode: nextMode,
          documentTitle: payload.document_title || c.documentTitle,
          messages: [...c.messages, assistantMsg],
          sources: nextSources,
          trace: nextTrace,
          updatedAt: Date.now(),
        }));
        setStatus("idle");
        setThinkingPhase("");
      } catch (err) {
        const errorMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content:
            "No he podido contactar con el backend de CyberGuide. Verifica que la API esté corriendo y que `VITE_API_BASE_URL` apunte a la URL correcta.",
          createdAt: Date.now(),
        };
        updateChat(activeChat.id, (c) => ({
          ...c,
          messages: [...c.messages, errorMsg],
          updatedAt: Date.now(),
        }));
        setStatus("error");
        setThinkingPhase("");
        console.error(err);
      }
    },
    [activeChat, updateChat],
  );

  /**
   * Edita un mensaje del usuario: trunca el chat hasta ese mensaje (inclusive),
   * sustituye su texto y regenera la respuesta. Guarda la versión previa como
   * snapshot navegable.
   */
  const editUserMessage = useCallback(
    async (userMsgId: string, newText: string) => {
      const trimmed = newText.trim();
      if (!trimmed || !activeChat) return;

      const idx = activeChat.messages.findIndex((m) => m.id === userMsgId);
      if (idx < 0) return;
      const branches = activeChat.branches ?? {};
      const existing = branches[userMsgId];
      if (existing && existing.editCount >= MAX_EDITS) return;

      // Snapshot del estado actual desde el user msg
      const currentSlice = activeChat.messages.slice(idx);
      const baseSnapshots: BranchSnapshot[] = existing?.snapshots ?? [{ items: currentSlice }];
      const editCount = (existing?.editCount ?? 0) + 1;
      const regenCount = existing?.regenCount ?? 0;

      const newUserMsg: ChatMessage = {
        ...currentSlice[0],
        content: trimmed,
        createdAt: Date.now(),
      };

      // Truncar y añadir nuevo user msg, re-mapeando branches al nuevo id (mismo)
      updateChat(activeChat.id, (c) => ({
        ...c,
        messages: [...c.messages.slice(0, idx), newUserMsg],
        updatedAt: Date.now(),
      }));

      setStatus("thinking");
      setThinkingPhase("Regenerando respuesta…");
      try {
        const payload = await callApi(activeChat.mode, trimmed, activeChat.sessionId, null);
        const assistantMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content: payload.answer || "",
          createdAt: Date.now(),
          trace: payload.trace ?? null,
          sources: payload.sources ?? [],
        };
        const newSnapshot: BranchSnapshot = { items: [newUserMsg, assistantMsg] };
        const snapshots = [...baseSnapshots, newSnapshot];
        const branchSet: BranchSet = {
          snapshots,
          index: snapshots.length - 1,
          editCount,
          regenCount,
        };

        updateChat(activeChat.id, (c) => ({
          ...c,
          messages: [...c.messages, assistantMsg],
          sources: payload.sources ?? c.sources,
          trace: payload.trace ?? c.trace,
          branches: { ...(c.branches ?? {}), [userMsgId]: branchSet },
          updatedAt: Date.now(),
        }));
        setStatus("idle");
        setThinkingPhase("");
      } catch (err) {
        setStatus("error");
        setThinkingPhase("");
        console.error(err);
      }
    },
    [activeChat, updateChat],
  );

  /**
   * Regenera una respuesta del asistente. Encuentra el user msg previo,
   * trunca y vuelve a llamar al backend.
   */
  const regenerateAssistant = useCallback(
    async (assistantMsgId: string) => {
      if (!activeChat) return;
      const aIdx = activeChat.messages.findIndex((m) => m.id === assistantMsgId);
      if (aIdx <= 0) return;
      const userMsg = activeChat.messages[aIdx - 1];
      if (userMsg.role !== "user") return;

      const branches = activeChat.branches ?? {};
      const existing = branches[userMsg.id];
      if (existing && existing.regenCount >= MAX_REGEN) return;

      const currentSlice = activeChat.messages.slice(aIdx - 1);
      const baseSnapshots: BranchSnapshot[] = existing?.snapshots ?? [{ items: currentSlice }];
      const editCount = existing?.editCount ?? 0;
      const regenCount = (existing?.regenCount ?? 0) + 1;

      // Truncar la respuesta actual
      updateChat(activeChat.id, (c) => ({
        ...c,
        messages: c.messages.slice(0, aIdx),
        updatedAt: Date.now(),
      }));

      setStatus("thinking");
      setThinkingPhase("Regenerando respuesta…");
      try {
        const payload = await callApi(activeChat.mode, userMsg.content, activeChat.sessionId, null);
        const assistantMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content: payload.answer || "",
          createdAt: Date.now(),
          trace: payload.trace ?? null,
          sources: payload.sources ?? [],
        };
        const newSnapshot: BranchSnapshot = { items: [userMsg, assistantMsg] };
        const snapshots = [...baseSnapshots, newSnapshot];
        const branchSet: BranchSet = {
          snapshots,
          index: snapshots.length - 1,
          editCount,
          regenCount,
        };

        updateChat(activeChat.id, (c) => ({
          ...c,
          messages: [...c.messages, assistantMsg],
          sources: payload.sources ?? c.sources,
          trace: payload.trace ?? c.trace,
          branches: { ...(c.branches ?? {}), [userMsg.id]: branchSet },
          updatedAt: Date.now(),
        }));
        setStatus("idle");
        setThinkingPhase("");
      } catch (err) {
        setStatus("error");
        setThinkingPhase("");
        console.error(err);
      }
    },
    [activeChat, updateChat],
  );

  /**
   * Cambia la versión visible de un turno. Reemplaza el slice desde el user msg
   * con el snapshot solicitado y trunca todo lo posterior.
   */
  const switchBranch = useCallback(
    (userMsgId: string, nextIndex: number) => {
      if (!activeChat) return;
      const branches = activeChat.branches ?? {};
      const set = branches[userMsgId];
      if (!set) return;
      const clamped = Math.max(0, Math.min(nextIndex, set.snapshots.length - 1));
      if (clamped === set.index) return;
      const idx = activeChat.messages.findIndex((m) => m.id === userMsgId);
      if (idx < 0) return;
      const snapshot = set.snapshots[clamped];
      updateChat(activeChat.id, (c) => ({
        ...c,
        messages: [...c.messages.slice(0, idx), ...snapshot.items],
        branches: { ...(c.branches ?? {}), [userMsgId]: { ...set, index: clamped } },
        updatedAt: Date.now(),
      }));
    },
    [activeChat, updateChat],
  );

  return {
    chats,
    activeChat,
    activeId,
    status,
    thinkingPhase,
    selectChat,
    createChat,
    deleteChat,
    renameChat,
    togglePinChat,
    toggleStarMessage,
    sendMessage,
    editUserMessage,
    regenerateAssistant,
    switchBranch,
  };
}
