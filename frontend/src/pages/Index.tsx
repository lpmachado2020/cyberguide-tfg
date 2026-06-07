import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence, LayoutGroup } from "framer-motion";
import { ShieldAlert, KeyRound, Mail, FileSearch } from "lucide-react";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { MessageList } from "@/components/chat/MessageList";
import { Composer } from "@/components/chat/Composer";
import { InspectorPanel } from "@/components/chat/InspectorPanel";
import { useChats } from "@/hooks/useChats";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { SideRail } from "@/components/chat/SideRail";
import { cn } from "@/lib/utils";

const QUICK_ACTIONS = [
  { icon: Mail, label: "Analizar un correo de phishing", action: "send" as const },
  { icon: KeyRound, label: "Mejorar mis contraseñas", action: "send" as const },
  { icon: ShieldAlert, label: "¿Qué hago si me han hackeado?", action: "send" as const },
  { icon: FileSearch, label: "Revisar un PDF sospechoso", action: "prefill" as const },
];

const Index = () => {
  const {
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
  } = useChats();

  const [sidebarPinned, setSidebarPinned] = useState(false);
  const [sidebarHover, setSidebarHover] = useState(false);
  const sidebarOpen = sidebarPinned || sidebarHover;
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorMessageId, setInspectorMessageId] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string>("");
  const [focusMessageId, setFocusMessageId] = useState<string | null>(null);

  function jumpToMessage(chatId: string, messageId: string) {
    selectChat(chatId);
    // Pequeño delay para asegurar que el chat se haya renderizado
    window.setTimeout(() => setFocusMessageId(messageId), 60);
  }

  // Pequeño retardo para evitar parpadeo al pasar entre el rail y el sidebar.
  const hoverLeaveTimer = useRef<number | null>(null);
  const cancelHoverLeave = () => {
    if (hoverLeaveTimer.current) {
      window.clearTimeout(hoverLeaveTimer.current);
      hoverLeaveTimer.current = null;
    }
  };
  const previewEnter = () => {
    cancelHoverLeave();
    setSidebarHover(true);
  };
  const previewLeave = () => {
    cancelHoverLeave();
    hoverLeaveTimer.current = window.setTimeout(() => setSidebarHover(false), 80);
  };
  // Si el ratón está sobre uno de los botones del rail, cancelamos la
  // expansión por hover: solo se abrirá si el usuario hace clic.
  const cancelHoverExpand = () => {
    cancelHoverLeave();
    setSidebarHover(false);
  };
  // Cualquier clic dentro del sidebar lo "ancla" (queda fijo abierto).
  const pinSidebar = () => {
    cancelHoverLeave();
    setSidebarPinned(true);
  };

  // ≥1280px: ambos sidebars pueden coexistir. Debajo: solo uno a la vez.
  const isWide = useMediaQuery("(min-width: 1280px)");
  // ≥768px (tablet+): el sidebar empuja contenido. <768px (móvil): overlay.
  const isTabletUp = useMediaQuery("(min-width: 768px)");

  // Si pasamos de wide a estrecho con ambos abiertos, cerramos el inspector.
  useEffect(() => {
    if (!isWide && sidebarOpen && inspectorOpen) setInspectorOpen(false);
  }, [isWide, sidebarOpen, inspectorOpen]);

  // ESC cierra el último abierto.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (inspectorOpen) setInspectorOpen(false);
      else if (sidebarPinned) {
        setSidebarPinned(false);
        setSidebarHover(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarPinned, inspectorOpen]);

  function openSidebar() {
    setSidebarPinned(true);
    setSidebarHover(false);
    if (!isWide) setInspectorOpen(false);
  }
  function closeSidebar() {
    setSidebarPinned(false);
    setSidebarHover(false);
  }
  function openInspector() {
    setInspectorOpen(true);
    if (!isWide) {
      setSidebarPinned(false);
      setSidebarHover(false);
    }
  }

  if (!activeChat) return null;

  const isThinking = status === "thinking";
  const isEmpty = activeChat.messages.length === 0 && !isThinking;
  // Scrim sólo cuando el sidebar/inspector está superpuesto (móvil) o en
  // pantallas estrechas con inspector abierto.
  const sidebarIsOverlay = !isTabletUp;
  const showScrim =
    (sidebarOpen && sidebarIsOverlay) || (inspectorOpen && !isWide);

  // Mensaje seleccionado para el inspector (con fallback al último del asistente)
  const lastAssistantMsg = [...activeChat.messages].reverse().find((m) => m.role === "assistant") ?? null;
  const inspectedMessage =
    activeChat.messages.find((m) => m.id === inspectorMessageId && m.role === "assistant") ??
    lastAssistantMsg;

  return (
    <div className="relative flex h-screen w-full overflow-hidden">
      {/* Mini-rail siempre visible cuando el sidebar está cerrado (sm+) */}
      {!sidebarOpen && (
        <SideRail
          onOpenSidebar={openSidebar}
          onCreate={() => {
            createChat();
            openSidebar();
          }}
          chats={chats}
          onSelectChat={(id) => {
            selectChat(id);
            openSidebar();
          }}
          onJumpToMessage={jumpToMessage}
          onHoverZoneEnter={previewEnter}
          onHoverZoneLeave={previewLeave}
        />
      )}

      {/* Scrim — sólo cuando el panel está superpuesto, cierra al click fuera */}
      <AnimatePresence>
        {showScrim && (
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={() => {
              closeSidebar();
              setInspectorOpen(false);
            }}
            className="cg-scrim absolute inset-0 z-20"
          />
        )}
      </AnimatePresence>

      {/* Left sidebar:
          - Móvil (<768px): overlay absolute con scrim.
          - Tablet/desktop (≥768px): empuja contenido (slot flex animado). */}
      <AnimatePresence initial={false}>
        {sidebarOpen && isTabletUp && (
          <motion.div
            key="left-sidebar-push"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 304, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.32, 0.72, 0, 1] }}
            onMouseEnter={previewEnter}
            onMouseLeave={previewLeave}
            onPointerDownCapture={pinSidebar}
            className="relative z-10 shrink-0 overflow-hidden py-3 pl-3"
          >
            <ChatSidebar
              chats={chats}
              activeId={activeId}
              onSelect={(id) => {
                selectChat(id);
                openSidebar();
                if (!isWide) setInspectorOpen(false);
              }}
              onCreate={() => {
                createChat();
                openSidebar();
              }}
              onDelete={deleteChat}
              onRename={renameChat}
              onTogglePin={togglePinChat}
              onJumpToMessage={jumpToMessage}
              onClose={closeSidebar}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {sidebarOpen && !isTabletUp && (
          <motion.div
            key="left-sidebar-overlay"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
            className="absolute inset-y-3 left-3 z-30"
          >
            <ChatSidebar
              chats={chats}
              activeId={activeId}
              onSelect={(id) => {
                selectChat(id);
                closeSidebar();
              }}
              onCreate={() => {
                createChat();
                closeSidebar();
              }}
              onDelete={deleteChat}
              onRename={renameChat}
              onTogglePin={togglePinChat}
              onJumpToMessage={jumpToMessage}
              onClose={closeSidebar}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main — desplazado para dejar sitio al mini-rail (sm+) */}
      <main
        className={cn(
          "flex min-w-0 flex-1 flex-col",
          !sidebarOpen && "sm:pl-14"
        )}
      >
        <ChatHeader
          title={isEmpty ? "CyberGuide" : activeChat.title}
          mode={activeChat.mode}
          documentTitle={activeChat.documentTitle}
          onOpenSidebar={openSidebar}
          showMobileMenu={!sidebarOpen}
          canManage={!isEmpty}
          onRename={(t) => renameChat(activeChat.id, t)}
          onDelete={() => deleteChat(activeChat.id)}
          chat={activeChat}
          onJumpToMessage={jumpToMessage}
        />

        <LayoutGroup>
          {isEmpty ? (
            <div className="flex flex-1 flex-col items-center justify-center px-6 pb-16">
              <motion.div
                key="hero"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
                className="w-full max-w-2xl"
              >
                <h1
                  className="mb-10 text-center text-[2.4rem] font-semibold leading-[1.1] tracking-[-0.01em] text-foreground/90 sm:text-[2.9rem]"
                  style={{ fontFamily: "'Chakra Petch', sans-serif" }}
                >
                  ¿En qué te ayudo hoy?
                </h1>

                <motion.div layoutId="composer" transition={{ duration: 0.45, ease: [0.32, 0.72, 0, 1] }}>
                  <Composer
                    onSend={(t, f) => {
                      sendMessage(t, f);
                      setPendingPrompt("");
                    }}
                    disabled={isThinking}
                    autoFocus
                    initialText={pendingPrompt}
                  />
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15, duration: 0.4 }}
                  className="mt-5 flex flex-wrap justify-center gap-2"
                >
                  {QUICK_ACTIONS.map(({ icon: Icon, label, action }) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => {
                        if (isThinking) return;
                        if (action === "send") {
                          void sendMessage(label, null);
                          setPendingPrompt("");
                          return;
                        }
                        setPendingPrompt(label);
                      }}
                      className="hover-surface group inline-flex items-center gap-2 rounded-full bg-foreground/[0.04] px-3.5 py-1.5 text-[0.82rem] text-foreground/75 transition-all"
                    >
                      <Icon className="h-3.5 w-3.5 text-foreground/55 transition-colors group-hover:text-foreground/80" strokeWidth={2} />
                      {label}
                    </button>
                  ))}
                </motion.div>
              </motion.div>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <MessageList
                messages={activeChat.messages}
                isThinking={isThinking}
                thinkingPhase={thinkingPhase}
                inspectorOpen={inspectorOpen}
                inspectorMessageId={inspectorMessageId ?? lastAssistantMsg?.id ?? null}
                onToggleInspector={(messageId) => {
                  const current = inspectorMessageId ?? lastAssistantMsg?.id ?? null;
                  if (inspectorOpen && current === messageId) {
                    setInspectorOpen(false);
                  } else {
                    setInspectorMessageId(messageId);
                    openInspector();
                  }
                }}
                branches={activeChat.branches}
                onEditUser={editUserMessage}
                onRegenerate={regenerateAssistant}
                onSwitchBranch={switchBranch}
                onToggleStar={(messageId) => toggleStarMessage(activeChat.id, messageId)}
                focusMessageId={focusMessageId}
                onFocusHandled={() => setFocusMessageId(null)}
                disabled={isThinking}
              />
              <motion.div
                layoutId="composer"
                transition={{ duration: 0.45, ease: [0.32, 0.72, 0, 1] }}
                className="mx-auto w-full max-w-3xl px-6 pb-6"
              >
                <Composer onSend={sendMessage} disabled={isThinking} />
              </motion.div>
            </div>
          )}
        </LayoutGroup>
      </main>

      {/* Right inspector overlay */}
      <AnimatePresence>
        {inspectorOpen && (
          <motion.div
            key="right-inspector"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
            className="absolute inset-y-3 right-3 z-30"
          >
            <InspectorPanel
              trace={inspectedMessage?.trace ?? activeChat.trace}
              sources={inspectedMessage?.sources ?? activeChat.sources}
              onClose={() => setInspectorOpen(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default Index;
