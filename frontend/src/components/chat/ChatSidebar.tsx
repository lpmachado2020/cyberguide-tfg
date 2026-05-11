import { CheckCheck, MoreHorizontal, Pencil, Pin, PinOff, Search, SquareCheck, SquarePen, Star, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Chat } from "@/types/chat";
import { cn } from "@/lib/utils";
import { ThemeSwitch } from "./ThemeSwitch";
import { Checkbox } from "@/components/ui/checkbox";
import { ChatSearchPopover } from "./ChatSearchPopover";
import { StarredPopover } from "./StarredPopover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface SidebarProps {
  chats: Chat[];
  activeId: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onRename?: (id: string, title: string) => void;
  onTogglePin?: (id: string) => void;
  onJumpToMessage?: (chatId: string, messageId: string) => void;
  onClose: () => void;
}

const PAGE_SIZE = 15;

function relativeTime(ts: number) {
  const m = Math.round((Date.now() - ts) / 60000);
  if (m < 1) return "ahora";
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.round(h / 24);
  return `${d}d`;
}

export function ChatSidebar({
  chats,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onRename,
  onTogglePin,
  onJumpToMessage,
  onClose,
}: SidebarProps) {
  const [filter, setFilter] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmBulk, setConfirmBulk] = useState(false);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lastSelectedId, setLastSelectedId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (renamingId) {
      const id = window.setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 50);
      return () => window.clearTimeout(id);
    }
  }, [renamingId]);


  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return chats
      .filter((c) => {
        // Ocultar chats vacíos del registro (salvo el activo)
        if ((c.messages?.length ?? 0) === 0 && c.id !== activeId) return false;
        if (!q) return true;
        if (c.title.toLowerCase().includes(q)) return true;
        return c.messages?.some((m) => m.content?.toLowerCase().includes(q));
      })
      .sort((a, b) => {
        // Fijados primero, ordenados por pinnedAt desc; resto por updatedAt desc
        if (a.pinned && !b.pinned) return -1;
        if (!a.pinned && b.pinned) return 1;
        if (a.pinned && b.pinned) return (b.pinnedAt ?? 0) - (a.pinnedAt ?? 0);
        return b.updatedAt - a.updatedAt;
      });
  }, [chats, filter, activeId]);

  // Reset visible count when filter changes
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [filter]);

  const visible = filtered.slice(0, visibleCount);
  const pinnedVisible = visible.filter((c) => c.pinned);
  const unpinnedVisible = visible.filter((c) => !c.pinned);
  const hasMore = visibleCount < filtered.length;
  const canShowLess = visibleCount > PAGE_SIZE;

  // Cmd/Ctrl+A to select all visible; Esc to exit select mode
  useEffect(() => {
    if (!selectMode) return;
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        setSelected(new Set(visible.map((c) => c.id)));
      } else if (e.key === "Escape") {
        exitSelectMode();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectMode, visible]);

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    if (!hasMore) return;
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
      setVisibleCount((v) => Math.min(v + PAGE_SIZE, filtered.length));
    }
  }

  function startRename(chat: Chat) {
    setDraft(chat.title);
    setRenamingId(chat.id);
  }

  function commitRename() {
    if (!renamingId) return;
    const next = draft.trim();
    const original = chats.find((c) => c.id === renamingId);
    if (next && original && next !== original.title) onRename?.(renamingId, next);
    setRenamingId(null);
  }

  function toggleSelect(
    id: string,
    opts?: { shift?: boolean; meta?: boolean },
  ) {
    if (opts?.shift && lastSelectedId && lastSelectedId !== id) {
      const ids = visible.map((c) => c.id);
      const a = ids.indexOf(lastSelectedId);
      const b = ids.indexOf(id);
      if (a !== -1 && b !== -1) {
        const [start, end] = a < b ? [a, b] : [b, a];
        const range = ids.slice(start, end + 1);
        setSelected((prev) => {
          const base = opts?.meta ? new Set(prev) : new Set<string>();
          range.forEach((rid) => base.add(rid));
          return base;
        });
        setLastSelectedId(id);
        return;
      }
    }
    if (opts?.meta) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      setLastSelectedId(id);
      return;
    }
    // Plain click: toggle (allow deselecting)
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id) && next.size === 1) {
        next.delete(id);
      } else {
        next.clear();
        next.add(id);
      }
      return next;
    });
    setLastSelectedId(id);
  }

  function exitSelectMode() {
    setSelectMode(false);
    setSelected(new Set());
    setLastSelectedId(null);
  }

  function enterSelectMode(initialId?: string) {
    setSelectMode(true);
    const initial = new Set<string>();
    if (initialId) initial.add(initialId);
    setSelected(initial);
    setLastSelectedId(initialId ?? null);
  }

  const allVisibleSelected =
    visible.length > 0 && visible.every((c) => selected.has(c.id));

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visible.map((c) => c.id)));
    }
  }

  function bulkDelete() {
    selected.forEach((id) => onDelete(id));
    exitSelectMode();
    setConfirmBulk(false);
  }

  function renderRow(chat: Chat) {
    const isActive = chat.id === activeId;
    const isRenaming = renamingId === chat.id;
    const isSelected = selected.has(chat.id);
    return (
      <div
        key={chat.id}
        className={cn(
          "group flex items-center rounded-2xl py-2 transition-colors mx-px my-px px-[12px] gap-[8px]",
          isActive && !selectMode
            ? "bg-primary/15 ring-1 ring-primary/30"
            : isSelected
              ? "bg-primary/10"
              : "hover:bg-primary/[0.08]"
        )}
      >
        {selectMode && (
          <span
            onClick={(e) => {
              e.stopPropagation();
              toggleSelect(chat.id, { shift: e.shiftKey, meta: e.metaKey || e.ctrlKey });
            }}
            className="inline-flex"
          >
            <Checkbox
              checked={isSelected}
              aria-label={`Seleccionar ${chat.title}`}
              tabIndex={-1}
            />
          </span>
        )}

        {isRenaming ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              else if (e.key === "Escape") setRenamingId(null);
            }}
            className="min-w-0 flex-1 bg-transparent px-0 py-1 text-sm font-medium text-foreground/90 outline-none focus:outline-none"
          />
        ) : (
          <button
            type="button"
            onClick={(e) => {
              if (selectMode) toggleSelect(chat.id, { shift: e.shiftKey, meta: e.metaKey || e.ctrlKey });
              else onSelect(chat.id);
            }}
            className="flex min-w-0 flex-1 flex-col items-start text-left"
          >
            <span
              className={cn(
                "flex w-full items-center gap-1.5 text-sm font-medium transition-colors",
                isActive && !selectMode ? "text-primary-ink" : "text-foreground/85"
              )}
            >
              {chat.pinned && (
                <Pin className="h-3 w-3 shrink-0 text-primary/70" strokeWidth={2.4} />
              )}
              <span className="line-clamp-1">{chat.title || "Nuevo chat"}</span>
            </span>
            <span className="text-[0.7rem] text-muted-foreground/70">
              {relativeTime(chat.updatedAt)}
            </span>
          </button>
        )}

        {!selectMode && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={(e) => e.stopPropagation()}
                aria-label="Opciones del chat"
                className={cn(
                  "hover-surface grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition",
                  "opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100 focus:opacity-100"
                )}
              >
                <MoreHorizontal className="h-4 w-4" strokeWidth={2} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-44"
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              {onTogglePin && (
                <DropdownMenuItem onSelect={() => onTogglePin(chat.id)}>
                  {chat.pinned ? (
                    <>
                      <PinOff className="mr-2 h-4 w-4" />
                      Desfijar
                    </>
                  ) : (
                    <>
                      <Pin className="mr-2 h-4 w-4" />
                      Fijar arriba
                    </>
                  )}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => startRename(chat)}>
                <Pencil className="mr-2 h-4 w-4" />
                Cambiar nombre
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => enterSelectMode(chat.id)}>
                <SquareCheck className="mr-2 h-4 w-4" />
                Seleccionar
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => setConfirmDeleteId(chat.id)}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Eliminar chat
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    );
  }


  return (
    <aside className="glass animate-slide-left flex h-full w-72 flex-col gap-3 rounded-[28px] p-4">
      <div className="flex items-center justify-between">
        <span className="px-2 text-sm font-semibold tracking-tight">Chats</span>
        <div className="flex items-center gap-1">
          {!selectMode ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Ocultar chats"
              title="Ocultar chats"
              className="hover-surface group/btn grid h-8 w-8 place-items-center rounded-full text-foreground/70 transition-transform duration-200 hover:scale-105 active:scale-95"
            >
              <X className="h-[18px] w-[18px] transition-transform duration-200 group-hover/btn:scale-110" strokeWidth={2.2} />
            </button>
          ) : (
            <button
              type="button"
              onClick={exitSelectMode}
              className="hover-surface rounded-full px-3 py-1 text-xs font-medium text-foreground/75"
            >
              Cancelar
            </button>
          )}
        </div>
      </div>

      {!selectMode && (
        <div className="flex flex-col gap-0.5">
          <button
            type="button"
            onClick={onCreate}
            className="group/row flex w-full items-center gap-2.5 rounded-2xl px-2.5 py-2 text-left text-sm font-medium text-primary-ink transition-colors hover:bg-primary/10"
          >
            <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-primary-foreground shadow-[0_4px_12px_-4px_hsl(var(--primary)/0.55)] transition-transform duration-200 group-hover/row:scale-105">
              <SquarePen className="h-[14px] w-[14px]" strokeWidth={2.2} />
            </span>
            Nuevo chat
          </button>
          <ChatSearchPopover
            chats={chats}
            onSelect={onSelect}
            trigger={
              <button
                type="button"
                className="group/row flex w-full items-center gap-2.5 rounded-2xl px-2.5 py-2 text-left text-sm text-foreground/80 transition-colors hover:bg-foreground/[0.06]"
              >
                <span className="grid h-7 w-7 place-items-center rounded-full text-foreground/65 transition-transform duration-200 group-hover/row:scale-110">
                  <Search className="h-[15px] w-[15px]" strokeWidth={2} />
                </span>
                <span className="flex-1">Buscar</span>
              </button>
            }
          />
          <StarredPopover
            chats={chats}
            onSelect={(chatId, messageId) => {
              onSelect(chatId);
              onJumpToMessage?.(chatId, messageId);
            }}
            trigger={
              <button
                type="button"
                className="group/row flex w-full items-center gap-2.5 rounded-2xl px-2.5 py-2 text-left text-sm text-foreground/80 transition-colors hover:bg-foreground/[0.06]"
              >
                <span className="grid h-7 w-7 place-items-center rounded-full text-foreground/65 transition-transform duration-200 group-hover/row:scale-110">
                  <Star className="h-[15px] w-[15px]" strokeWidth={2} />
                </span>
                <span className="flex-1">Destacados</span>
              </button>
            }
          />
        </div>
      )}

      {selectMode && (
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={toggleSelectAllVisible}
            className="hover-surface inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-foreground/70"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            {allVisibleSelected ? "Deseleccionar todo" : "Seleccionar todo"}
          </button>
          <span>{selected.size} seleccionados</span>
        </div>
      )}

      <div
        ref={listRef}
        onScroll={handleScroll}
        className="cg-scroll flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto"
      >
        {filtered.length === 0 ? (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground/70">
            Sin conversaciones
          </p>
        ) : (
          <>
            {pinnedVisible.length > 0 && (
              <div className="mt-1 flex items-center gap-1.5 px-3 pb-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/60">
                <Pin className="h-3 w-3" strokeWidth={2.4} />
                Fijados
              </div>
            )}
            {pinnedVisible.map((chat) => renderRow(chat))}

            {pinnedVisible.length > 0 && unpinnedVisible.length > 0 && (
              <div className="mx-3 my-1 border-t border-foreground/5" />
            )}

            {pinnedVisible.length > 0 && unpinnedVisible.length > 0 && (
              <div className="px-3 pb-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/60">
                Recientes
              </div>
            )}

            {unpinnedVisible.map((chat) => renderRow(chat))}

            {(hasMore || canShowLess) && (
              <div className="flex items-center justify-center gap-2 px-2 py-2">
                {hasMore && (
                  <button
                    type="button"
                    onClick={() =>
                      setVisibleCount((v) => Math.min(v + PAGE_SIZE, filtered.length))
                    }
                    className="hover-surface rounded-full px-3 py-1 text-xs text-foreground/70"
                  >
                    Ver más
                  </button>
                )}
                {canShowLess && (
                  <button
                    type="button"
                    onClick={() => {
                      setVisibleCount(PAGE_SIZE);
                      listRef.current?.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                    className="hover-surface rounded-full px-3 py-1 text-xs text-foreground/70"
                  >
                    Ver menos
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {selectMode && selected.size > 0 && (
        <button
          type="button"
          onClick={() => setConfirmBulk(true)}
          className="flex items-center justify-center gap-2 rounded-full bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground transition hover:bg-destructive/90"
        >
          <Trash2 className="h-4 w-4" />
          Eliminar ({selected.size})
        </button>
      )}

      <div className="mt-2 border-t border-foreground/5 pt-3">
        <ThemeSwitch />
      </div>

      <AlertDialog
        open={confirmDeleteId !== null}
        onOpenChange={(o) => !o && setConfirmDeleteId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar este chat?</AlertDialogTitle>
            <AlertDialogDescription>
              Se borrará la conversación y sus mensajes. Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmDeleteId) onDelete(confirmDeleteId);
                setConfirmDeleteId(null);
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmBulk} onOpenChange={setConfirmBulk}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar {selected.size} chats?</AlertDialogTitle>
            <AlertDialogDescription>
              Se borrarán todas las conversaciones seleccionadas y sus mensajes. Esta
              acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={bulkDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}
