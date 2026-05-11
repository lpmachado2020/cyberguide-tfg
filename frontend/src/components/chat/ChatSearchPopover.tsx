import { MessageSquare, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { Chat } from "@/types/chat";
import { cn } from "@/lib/utils";

interface Props {
  chats: Chat[];
  onSelect: (id: string, messageId?: string) => void;
  trigger?: React.ReactNode;
  /** Limita la búsqueda de mensajes a un solo chat. */
  scopeChatId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

type Bucket = { label: string; items: Chat[] };

function bucketize(chats: Chat[]): Bucket[] {
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const todayMs = startOfToday.getTime();

  const buckets: Record<string, Chat[]> = {
    Hoy: [],
    Ayer: [],
    "Últimos 7 días": [],
    "Últimos 30 días": [],
    Anterior: [],
  };

  for (const c of chats) {
    if (c.updatedAt >= todayMs) buckets.Hoy.push(c);
    else if (c.updatedAt >= todayMs - day) buckets.Ayer.push(c);
    else if (now - c.updatedAt < 7 * day) buckets["Últimos 7 días"].push(c);
    else if (now - c.updatedAt < 30 * day) buckets["Últimos 30 días"].push(c);
    else buckets.Anterior.push(c);
  }

  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({
      label,
      items: items.sort((a, b) => b.updatedAt - a.updatedAt),
    }));
}

function highlight(text: string, q: string) {
  if (!q) return text;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-primary/25 px-0.5 text-foreground">
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  );
}

function snippet(content: string, q: string, len = 80) {
  const idx = content.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return content.slice(0, len);
  const start = Math.max(0, idx - 24);
  const end = Math.min(content.length, idx + q.length + len - (idx - start));
  return (start > 0 ? "…" : "") + content.slice(start, end) + (end < content.length ? "…" : "");
}

export function ChatSearchPopover({ chats, onSelect, trigger, scopeChatId, open: openProp, onOpenChange }: Props) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = openProp ?? internalOpen;
  const setOpen = (v: boolean | ((o: boolean) => boolean)) => {
    setInternalOpen((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      onOpenChange?.(next);
      return next;
    });
  };
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const scopedChats = useMemo(
    () => (scopeChatId ? chats.filter((c) => c.id === scopeChatId) : chats),
    [chats, scopeChatId],
  );

  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => inputRef.current?.focus(), 30);
      return () => window.clearTimeout(t);
    } else {
      setQ("");
    }
  }, [open]);

  // Atajo Cmd/Ctrl+K sólo en modo global (sin scope).
  useEffect(() => {
    if (scopeChatId) return;
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scopeChatId]);

  const buckets = useMemo(() => bucketize(scopedChats), [scopedChats]);

  const messageHits = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return [];
    const hits: { chat: Chat; messageId: string; content: string }[] = [];
    for (const c of scopedChats) {
      for (const m of c.messages ?? []) {
        if (m.content?.toLowerCase().includes(query)) {
          hits.push({ chat: c, messageId: m.id, content: m.content });
        }
      }
    }
    return hits.slice(0, 30);
  }, [scopedChats, q]);

  const chatHits = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query || scopeChatId) return [];
    return scopedChats
      .filter((c) => c.title.toLowerCase().includes(query))
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, 20);
  }, [scopedChats, q, scopeChatId]);

  function pick(id: string, messageId?: string) {
    onSelect(id, messageId);
    setOpen(false);
  }

  const defaultTrigger = (
    <button
      type="button"
      aria-label="Buscar"
      title="Buscar (⌘K)"
      className="hover-surface group/btn grid h-8 w-8 place-items-center rounded-full text-foreground/70 transition-transform duration-200 hover:scale-105 active:scale-95"
    >
      <Search className="h-[16px] w-[16px] transition-transform duration-300 group-hover/btn:scale-110 group-hover/btn:-rotate-6" strokeWidth={2.2} />
    </button>
  );

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger asChild>
        {trigger ?? defaultTrigger}
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-background/40 backdrop-blur-sm",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
          )}
        />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className={cn(
            "glass fixed left-1/2 top-[18%] z-50 w-[92vw] max-w-[560px] -translate-x-1/2",
            "rounded-2xl border border-foreground/5 p-0 shadow-2xl outline-none",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
          )}
        >
          <DialogPrimitive.Title className="sr-only">
            Buscar chats y mensajes
          </DialogPrimitive.Title>

          <div className="relative border-b border-foreground/5 p-3">
            <Search className="pointer-events-none absolute left-5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar chats y mensajes"
              className="w-full rounded-full bg-foreground/5 py-2 pl-9 pr-4 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          <div className="cg-scroll max-h-[60vh] overflow-y-auto p-2">
            {!q.trim() ? (
              buckets.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground/70">
                  Sin conversaciones
                </p>
              ) : (
                buckets.map((b) => (
                  <div key={b.label} className="mb-2">
                    <div className="px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/70">
                      {b.label}
                    </div>
                    {b.items.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => pick(c.id)}
                        className="hover-surface flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-sm"
                      >
                        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground/70" />
                        <span className="line-clamp-1 flex-1 text-foreground/85">
                          {c.title || "Nuevo chat"}
                        </span>
                      </button>
                    ))}
                  </div>
                ))
              )
            ) : chatHits.length === 0 && messageHits.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground/70">
                Sin resultados
              </p>
            ) : (
              <>
                {chatHits.length > 0 && (
                  <div className="mb-2">
                    <div className="px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/70">
                      Chats
                    </div>
                    {chatHits.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => pick(c.id)}
                        className="hover-surface flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-sm"
                      >
                        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground/70" />
                        <span className="line-clamp-1 flex-1 text-foreground/85">
                          {highlight(c.title || "Nuevo chat", q)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {messageHits.length > 0 && (
                  <div className="mb-1">
                    <div className="px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/70">
                      Mensajes
                    </div>
                    {messageHits.map((h) => (
                      <button
                        key={`${h.chat.id}-${h.messageId}`}
                        type="button"
                        onClick={() => pick(h.chat.id, h.messageId)}
                        className="hover-surface flex w-full flex-col items-start gap-0.5 rounded-xl px-2 py-1.5 text-left"
                      >
                        <span className="line-clamp-1 text-xs text-muted-foreground/80">
                          {h.chat.title || "Nuevo chat"}
                        </span>
                        <span className="line-clamp-2 text-sm text-foreground/85">
                          {highlight(snippet(h.content, q), q)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
