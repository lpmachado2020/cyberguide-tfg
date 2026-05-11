import { PanelLeft, Search, SquarePen, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Chat } from "@/types/chat";
import { ChatSearchPopover } from "./ChatSearchPopover";
import { StarredPopover } from "./StarredPopover";

interface SideRailProps {
  onOpenSidebar: () => void;
  onCreate: () => void;
  chats: Chat[];
  onSelectChat: (id: string) => void;
  onJumpToMessage?: (chatId: string, messageId: string) => void;
  onHoverZoneEnter?: () => void;
  onHoverZoneLeave?: () => void;
}

export function SideRail({
  onOpenSidebar,
  onCreate,
  chats,
  onSelectChat,
  onJumpToMessage,
  onHoverZoneEnter,
  onHoverZoneLeave,
}: SideRailProps) {
  return (
    <div className="absolute inset-y-0 left-0 z-10 hidden w-14 flex-col items-stretch sm:flex">
      <div className="flex flex-col items-center gap-1 py-3">
        <RailButton onClick={onOpenSidebar} label="Mostrar chats">
          <PanelLeft className="h-[18px] w-[18px] transition-transform duration-200 group-hover/rb:scale-110" strokeWidth={2} />
        </RailButton>
        <RailButton onClick={onCreate} label="Nuevo chat">
          <SquarePen className="h-[17px] w-[17px] transition-transform duration-200 group-hover/rb:scale-110" strokeWidth={2} />
        </RailButton>
        <ChatSearchPopover
          chats={chats}
          onSelect={onSelectChat}
          trigger={
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              aria-label="Buscar"
              title="Buscar"
              className="hover-surface group/rb grid h-9 w-9 place-items-center rounded-full text-foreground/65 transition-all duration-200 hover:text-foreground hover:scale-105 active:scale-95"
            >
              <Search className="h-[17px] w-[17px] transition-transform duration-300 group-hover/rb:scale-110 group-hover/rb:-rotate-6" strokeWidth={2} />
            </button>
          }
        />
        <StarredPopover
          chats={chats}
          onSelect={(chatId, messageId) => {
            onSelectChat(chatId);
            onJumpToMessage?.(chatId, messageId);
          }}
          trigger={
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              aria-label="Destacados"
              title="Destacados"
              className="hover-surface group/rb grid h-9 w-9 place-items-center rounded-full text-foreground/65 transition-all duration-200 hover:text-foreground hover:scale-105 active:scale-95"
            >
              <Star className="h-[17px] w-[17px] transition-transform duration-200 group-hover/rb:scale-110" strokeWidth={2} />
            </button>
          }
        />
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label="Mostrar chats"
        onClick={onOpenSidebar}
        onMouseEnter={onHoverZoneEnter}
        onMouseLeave={onHoverZoneLeave}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpenSidebar();
          }
        }}
        className="flex-1 cursor-pointer transition-colors hover:bg-foreground/[0.04] focus-visible:bg-foreground/[0.04] focus-visible:outline-none"
      />
    </div>
  );
}

function RailButton({
  onClick,
  label,
  children,
  active,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      aria-label={label}
      title={label}
      className={cn(
        "hover-surface group/rb grid h-9 w-9 place-items-center rounded-full text-foreground/65 transition-all duration-200 hover:text-foreground hover:scale-105 active:scale-95",
        active && "bg-foreground/8 text-foreground"
      )}
    >
      {children}
    </button>
  );
}
