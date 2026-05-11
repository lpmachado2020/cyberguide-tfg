import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Pencil, RefreshCw, Star } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BranchSet, ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";
import { MAX_EDITS, MAX_REGEN } from "@/hooks/useChats";

interface MessageListProps {
  messages: ChatMessage[];
  isThinking: boolean;
  thinkingPhase: string;
  inspectorOpen: boolean;
  inspectorMessageId: string | null;
  onToggleInspector: (messageId: string) => void;
  branches?: Record<string, BranchSet>;
  onEditUser?: (userMsgId: string, newText: string) => void;
  onRegenerate?: (assistantMsgId: string) => void;
  onSwitchBranch?: (userMsgId: string, nextIndex: number) => void;
  onToggleStar?: (messageId: string) => void;
  /** Si se establece, hace scroll y resalta brevemente ese mensaje. */
  focusMessageId?: string | null;
  onFocusHandled?: () => void;
  disabled?: boolean;
}

export function MessageList({
  messages,
  isThinking,
  thinkingPhase,
  inspectorOpen,
  inspectorMessageId,
  onToggleInspector,
  branches = {},
  onEditUser,
  onRegenerate,
  onSwitchBranch,
  onToggleStar,
  focusMessageId,
  onFocusHandled,
  disabled,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isThinking, thinkingPhase]);

  useEffect(() => {
    if (!focusMessageId) return;
    const el = containerRef.current?.querySelector<HTMLElement>(
      `[data-msg-id="${focusMessageId}"]`,
    );
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightId(focusMessageId);
      const t = window.setTimeout(() => setHighlightId(null), 2000);
      onFocusHandled?.();
      return () => window.clearTimeout(t);
    }
  }, [focusMessageId, onFocusHandled]);

  return (
    <div ref={containerRef} className="cg-scroll flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
        {messages.map((m, i) => {
          const prevUser =
            m.role === "assistant" && i > 0 && messages[i - 1].role === "user"
              ? messages[i - 1]
              : null;
          const ownerUserId = m.role === "user" ? m.id : prevUser?.id ?? null;
          const branch = ownerUserId ? branches[ownerUserId] : undefined;
          return (
            <Bubble
              key={m.id}
              message={m}
              showInspectorToggle={m.role === "assistant"}
              inspectorOpen={inspectorOpen && inspectorMessageId === m.id}
              onToggleInspector={() => onToggleInspector(m.id)}
              branch={branch}
              ownerUserId={ownerUserId}
              onEditUser={onEditUser}
              onRegenerate={onRegenerate}
              onSwitchBranch={onSwitchBranch}
              onToggleStar={onToggleStar}
              highlighted={highlightId === m.id}
              disabled={disabled}
            />
          );
        })}
        {isThinking && <ThinkingBubble phase={thinkingPhase} />}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function Bubble({
  message,
  showInspectorToggle,
  inspectorOpen,
  onToggleInspector,
  branch,
  ownerUserId,
  onEditUser,
  onRegenerate,
  onSwitchBranch,
  onToggleStar,
  highlighted,
  disabled,
}: {
  message: ChatMessage;
  showInspectorToggle: boolean;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  branch?: BranchSet;
  ownerUserId: string | null;
  onEditUser?: (userMsgId: string, newText: string) => void;
  onRegenerate?: (assistantMsgId: string) => void;
  onSwitchBranch?: (userMsgId: string, nextIndex: number) => void;
  onToggleStar?: (messageId: string) => void;
  highlighted?: boolean;
  disabled?: boolean;
}) {
  const isUser = message.role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) {
      const t = window.setTimeout(() => {
        const el = taRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
          el.style.height = "auto";
          el.style.height = el.scrollHeight + "px";
        }
      }, 30);
      return () => window.clearTimeout(t);
    }
  }, [editing]);

  function startEdit() {
    setDraft(message.content);
    setEditing(true);
  }

  function commitEdit() {
    const next = draft.trim();
    if (!next || next === message.content) {
      setEditing(false);
      return;
    }
    onEditUser?.(message.id, next);
    setEditing(false);
  }

  const editsLeft = branch ? MAX_EDITS - branch.editCount : MAX_EDITS;
  const regensLeft = branch ? MAX_REGEN - branch.regenCount : MAX_REGEN;
  const canEdit = isUser && editsLeft > 0 && !disabled;
  const canRegen = !isUser && regensLeft > 0 && !disabled;

  return (
    <article
      data-msg-id={message.id}
      className={cn(
        "group/bubble animate-fade-in text-[0.96rem] scroll-mt-20 transition-shadow duration-500",
        highlighted && "rounded-3xl ring-2 ring-amber-400/70 ring-offset-2 ring-offset-background",
        isUser
          ? cn(
              "ml-auto flex flex-col items-end",
              editing ? "w-full" : "max-w-[78%]",
            )
          : "mr-auto max-w-full text-foreground",
      )}
    >
      <div
        className={cn(
          isUser
            ? "rounded-3xl rounded-br-md bg-[hsl(var(--user-bubble))] px-4 py-2.5 text-[hsl(var(--user-bubble-foreground))]"
            : "",
          isUser && editing && "w-full",
        )}
      >
        {isUser ? (
          editing ? (
            <div className="flex flex-col gap-2">
              <textarea
                ref={taRef}
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  e.currentTarget.style.height = "auto";
                  e.currentTarget.style.height = e.currentTarget.scrollHeight + "px";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    commitEdit();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setEditing(false);
                  }
                }}
                rows={1}
                className="w-full resize-none bg-transparent leading-relaxed outline-none placeholder:text-[hsl(var(--user-bubble-foreground))]/50"
              />
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="rounded-full px-3 py-1 text-xs text-[hsl(var(--user-bubble-foreground))]/80 hover:bg-foreground/10"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={commitEdit}
                  disabled={!draft.trim()}
                  className="rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground transition hover:bg-primary-strong disabled:opacity-40"
                >
                  Enviar
                </button>
              </div>
            </div>
          ) : (
            <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
          )
        ) : (
          <>
            {showInspectorToggle && (
              <InspectorToggle open={inspectorOpen} onClick={onToggleInspector} />
            )}
            <div className="md-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          </>
        )}
      </div>

      {!editing && (
        <MessageToolbar
          align={isUser ? "right" : "left"}
          content={message.content}
          branch={branch}
          ownerUserId={ownerUserId}
          onSwitchBranch={onSwitchBranch}
          onEdit={canEdit ? startEdit : undefined}
          onRegenerate={canRegen ? () => onRegenerate?.(message.id) : undefined}
          onToggleStar={onToggleStar ? () => onToggleStar(message.id) : undefined}
          starred={!!message.starred}
          editsLeft={editsLeft}
          regensLeft={regensLeft}
          isUser={isUser}
        />
      )}
    </article>
  );
}

function MessageToolbar({
  align,
  content,
  branch,
  ownerUserId,
  onSwitchBranch,
  onEdit,
  onRegenerate,
  onToggleStar,
  starred,
  editsLeft,
  regensLeft,
  isUser,
}: {
  align: "left" | "right";
  content: string;
  branch?: BranchSet;
  ownerUserId: string | null;
  onSwitchBranch?: (userMsgId: string, nextIndex: number) => void;
  onEdit?: () => void;
  onRegenerate?: () => void;
  onToggleStar?: () => void;
  starred?: boolean;
  editsLeft: number;
  regensLeft: number;
  isUser: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* noop */
    }
  }

  const total = branch?.snapshots.length ?? 0;
  const idx = branch?.index ?? 0;
  const showSwitcher = total > 1 && ownerUserId;

  return (
    <div
      className={cn(
        "mt-1 flex items-center gap-0.5 text-muted-foreground/80 transition-opacity",
        starred
          ? "opacity-100"
          : "opacity-0 group-hover/bubble:opacity-100 focus-within:opacity-100",
        align === "right" ? "justify-end pr-1" : "justify-start pl-0.5",
      )}
    >
      {showSwitcher && (
        <div className="mr-1 inline-flex items-center gap-0.5 rounded-full bg-foreground/[0.04] px-1 py-0.5 text-[0.7rem] text-foreground/65">
          <button
            type="button"
            onClick={() => onSwitchBranch?.(ownerUserId!, idx - 1)}
            disabled={idx <= 0}
            aria-label="Versión anterior"
            className="grid h-5 w-5 place-items-center rounded-full hover:bg-foreground/10 disabled:opacity-30"
          >
            <ChevronLeft className="h-3 w-3" />
          </button>
          <span className="tabular-nums">
            {idx + 1}/{total}
          </span>
          <button
            type="button"
            onClick={() => onSwitchBranch?.(ownerUserId!, idx + 1)}
            disabled={idx >= total - 1}
            aria-label="Versión siguiente"
            className="grid h-5 w-5 place-items-center rounded-full hover:bg-foreground/10 disabled:opacity-30"
          >
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      )}

      <ToolbarButton onClick={copy} label={copied ? "Copiado" : "Copiar"}>
        {copied ? (
          <Check className="h-3.5 w-3.5 animate-scale-in text-primary" />
        ) : (
          <Copy className="h-3.5 w-3.5 transition-transform duration-200 group-hover/tb:scale-110 group-active/tb:scale-95" />
        )}
      </ToolbarButton>

      {onToggleStar && (
        <ToolbarButton
          onClick={onToggleStar}
          label={starred ? "Quitar destacado" : "Destacar mensaje"}
          active={starred}
        >
          <Star
            className={cn(
              "h-3.5 w-3.5 transition-transform duration-200 group-hover/tb:scale-110 group-active/tb:scale-95",
              starred && "fill-amber-400 text-amber-400",
            )}
          />
        </ToolbarButton>
      )}

      {isUser && onEdit && (
        <ToolbarButton onClick={onEdit} label={`Editar (${editsLeft} restantes)`}>
          <Pencil className="h-3.5 w-3.5 transition-transform duration-200 group-hover/tb:-rotate-12 group-hover/tb:scale-110 group-active/tb:scale-95" />
        </ToolbarButton>
      )}

      {!isUser && onRegenerate && (
        <ToolbarButton onClick={onRegenerate} label={`Regenerar (${regensLeft} restantes)`}>
          <RefreshCw className="h-3.5 w-3.5 transition-transform duration-500 group-hover/tb:rotate-180 group-active/tb:scale-95" />
        </ToolbarButton>
      )}

      {isUser && !onEdit && editsLeft <= 0 && (
        <span className="px-1.5 text-[0.7rem] text-muted-foreground/60">Máx. ediciones</span>
      )}
      {!isUser && !onRegenerate && regensLeft <= 0 && (
        <span className="px-1.5 text-[0.7rem] text-muted-foreground/60">Máx. regeneraciones</span>
      )}
    </div>
  );
}

function ToolbarButton({
  onClick,
  label,
  active,
  children,
}: {
  onClick: () => void;
  label: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "hover-surface group/tb grid h-7 w-7 place-items-center rounded-full transition-colors hover:text-foreground",
        active ? "text-amber-500 opacity-100" : "text-foreground/65",
      )}
    >
      {children}
    </button>
  );
}

function InspectorToggle({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={open ? "Ocultar proceso y fuentes" : "Ver proceso y fuentes"}
      title={open ? "Ocultar detalles" : "Ver detalles del razonamiento"}
      className="mb-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-foreground/40 transition-colors hover:text-foreground/80"
    >
      <ChevronDown
        className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")}
        strokeWidth={2.6}
      />
    </button>
  );
}

function ThinkingBubble({ phase }: { phase: string }) {
  return (
    <article className="animate-fade-in mr-auto">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{phase || "Pensando"}</span>
        <span className="flex items-center gap-1">
          <span className="thinking-dot" />
          <span className="thinking-dot" />
          <span className="thinking-dot" />
        </span>
      </div>
    </article>
  );
}
