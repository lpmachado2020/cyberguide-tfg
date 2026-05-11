import { MessageSquare, Star } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { Chat, ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";

interface Props {
  chats: Chat[];
  scopeChatId?: string;
  onSelect: (chatId: string, messageId: string) => void;
  trigger?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

interface Hit {
  chat: Chat;
  message: ChatMessage;
}

function snippet(content: string, q: string, len = 120) {
  if (!q) return content.length > len ? content.slice(0, len) + "…" : content;
  const idx = content.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return content.slice(0, len) + (content.length > len ? "…" : "");
  const start = Math.max(0, idx - 24);
  const end = Math.min(content.length, idx + q.length + len - (idx - start));
  return (start > 0 ? "…" : "") + content.slice(start, end) + (end < content.length ? "…" : "");
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

function relativeDate(ts: number) {
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

export function StarredPopover({ chats, scopeChatId, onSelect, trigger, open: openProp, onOpenChange }: Props) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = openProp ?? internalOpen;
  const setOpen = (v: boolean) => {
    setInternalOpen(v);
    onOpenChange?.(v);
  };
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => inputRef.current?.focus(), 30);
      return () => window.clearTimeout(t);
    } else {
      setQ("");
    }
  }, [open]);

  const hits = useMemo<Hit[]>(() => {
    const source = scopeChatId ? chats.filter((c) => c.id === scopeChatId) : chats;
    const all: Hit[] = [];
    for (const c of source) {
      for (const m of c.messages ?? []) {
        if (m.starred) all.push({ chat: c, message: m });
      }
    }
    const query = q.trim().toLowerCase();
    const filtered = query
      ? all.filter(
          (h) =>
            h.message.content?.toLowerCase().includes(query) ||
            h.chat.title?.toLowerCase().includes(query),
        )
      : all;
    return filtered.sort(
      (a, b) =>
        (b.message.starredAt ?? b.message.createdAt) -
        (a.message.starredAt ?? a.message.createdAt),
    );
  }, [chats, scopeChatId, q]);

  function pick(h: Hit) {
    onSelect(h.chat.id, h.message.id);
    setOpen(false);
  }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-background/40 backdrop-blur-sm",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
          )}
        />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className={cn(
            "glass fixed left-1/2 top-[14%] z-50 w-[92vw] max-w-[600px] -translate-x-1/2",
            "rounded-2xl border border-foreground/5 p-0 shadow-2xl outline-none",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
          )}
        >
          <DialogPrimitive.Title className="flex items-center gap-2 border-b border-foreground/5 px-4 py-3 text-sm font-medium text-foreground/85">
            <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
            {scopeChatId ? "Destacados del chat" : "Mensajes destacados"}
            <span className="ml-auto text-xs font-normal text-muted-foreground/70">
              {hits.length}
            </span>
          </DialogPrimitive.Title>

          <div className="border-b border-foreground/5 p-3">
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filtrar destacados…"
              className="w-full rounded-full bg-foreground/5 px-4 py-2 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          <div className="cg-scroll max-h-[60vh] overflow-y-auto p-2">
            {hits.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
                <Star className="h-6 w-6 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground/70">
                  {q
                    ? "Sin coincidencias"
                    : scopeChatId
                      ? "Aún no has destacado mensajes en este chat"
                      : "Aún no has destacado ningún mensaje"}
                </p>
                {!q && (
                  <p className="max-w-[36ch] text-xs text-muted-foreground/60">
                    Pulsa la estrella ⭐ junto a cualquier mensaje para guardarlo aquí.
                  </p>
                )}
              </div>
            ) : (
              hits.map((h) => (
                <button
                  key={`${h.chat.id}-${h.message.id}`}
                  type="button"
                  onClick={() => pick(h)}
                  className="hover-surface flex w-full flex-col items-start gap-1 rounded-xl px-3 py-2 text-left"
                >
                  <span className="flex w-full items-center gap-1.5 text-[0.7rem] text-muted-foreground/80">
                    <MessageSquare className="h-3 w-3" />
                    <span className="line-clamp-1 flex-1">
                      {h.chat.title || "Nuevo chat"}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {relativeDate(h.message.starredAt ?? h.message.createdAt)}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "line-clamp-3 text-sm leading-snug pr-4 text-foreground/85",
                      h.message.role === "user" && "italic text-foreground/75",
                    )}
                  >
                    {highlight(snippet(h.message.content, q), q)}
                  </span>
                </button>
              ))
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
