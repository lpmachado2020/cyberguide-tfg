import { MoreHorizontal, PanelLeft, Pencil, Search, Star, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Chat, ChatMode } from "@/types/chat";
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

interface ChatHeaderProps {
  title: string;
  mode: ChatMode;
  documentTitle?: string;
  onOpenSidebar?: () => void;
  showMobileMenu?: boolean;
  onRename?: (title: string) => void;
  onDelete?: () => void;
  canManage?: boolean;
  chat?: Chat;
  onJumpToMessage?: (chatId: string, messageId: string) => void;
}

export function ChatHeader({
  title,
  mode,
  documentTitle,
  onOpenSidebar,
  showMobileMenu,
  onRename,
  onDelete,
  canManage,
  chat,
  onJumpToMessage,
}: ChatHeaderProps) {
  const modeLabel =
    (mode === "pdf" || mode === "image") && documentTitle ? documentTitle : null;

  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(title);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [starredOpen, setStarredOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renaming) {
      setDraft(title);
      const id = window.setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 50);
      return () => window.clearTimeout(id);
    }
  }, [renaming, title]);

  function commitRename() {
    const next = draft.trim();
    if (next && next !== title) onRename?.(next);
    setRenaming(false);
  }

  return (
    <header className="relative flex items-center justify-center gap-4 px-5 py-3">
      {showMobileMenu && (
        <button
          type="button"
          onClick={onOpenSidebar}
          aria-label="Mostrar chats"
          className="hover-surface absolute left-3 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-foreground/70 sm:hidden"
        >
          <PanelLeft className="h-[18px] w-[18px]" strokeWidth={2} />
        </button>
      )}
      <div className="min-w-0 flex-1 text-center">
        {renaming ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              else if (e.key === "Escape") setRenaming(false);
            }}
            className="mx-auto block w-full max-w-sm rounded-md bg-foreground/5 px-2 py-1 text-center text-sm font-medium tracking-tight text-foreground/90 outline-none ring-1 ring-primary/30 focus:ring-2"
          />
        ) : (
          <h2 className="line-clamp-1 text-sm font-medium tracking-tight text-foreground/80">
            {title || "CyberGuide"}
            {modeLabel && (
              <span className="ml-2 text-muted-foreground/70">· {modeLabel}</span>
            )}
          </h2>
        )}
      </div>

      {canManage && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Opciones del chat"
                className="hover-surface grid h-9 w-9 place-items-center rounded-full text-foreground/70"
              >
                <MoreHorizontal className="h-[18px] w-[18px]" strokeWidth={2} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-44"
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              <DropdownMenuItem onSelect={() => setRenaming(true)}>
                <Pencil className="mr-2 h-4 w-4" />
                Cambiar nombre
              </DropdownMenuItem>
              {chat && (
                <DropdownMenuItem onSelect={() => setSearchOpen(true)}>
                  <Search className="mr-2 h-4 w-4" />
                  Buscar en el chat
                </DropdownMenuItem>
              )}
              {chat && (
                <DropdownMenuItem onSelect={() => setStarredOpen(true)}>
                  <Star className="mr-2 h-4 w-4" />
                  Ver destacados
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => setConfirmOpen(true)}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Eliminar chat
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
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
                setConfirmOpen(false);
                onDelete?.();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {chat && (
        <ChatSearchPopover
          chats={[chat]}
          scopeChatId={chat.id}
          open={searchOpen}
          onOpenChange={setSearchOpen}
          onSelect={(chatId, messageId) => {
            if (messageId) onJumpToMessage?.(chatId, messageId);
          }}
          trigger={<></>}
        />
      )}
      {chat && (
        <StarredPopover
          chats={[chat]}
          scopeChatId={chat.id}
          open={starredOpen}
          onOpenChange={setStarredOpen}
          onSelect={(chatId, messageId) => onJumpToMessage?.(chatId, messageId)}
        />
      )}
    </header>
  );
}
