import { ArrowUp, FileText, ImageIcon, Plus, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface ComposerProps {
  onSend: (text: string, file: File | null) => void;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  initialText?: string;
}

const ACCEPTED = ["application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"];

export function Composer({
  onSend,
  disabled,
  placeholder = "Pregunta lo que quieras",
  autoFocus,
  initialText,
}: ComposerProps) {
  const [text, setText] = useState(initialText ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [popoverDragOver, setPopoverDragOver] = useState(false);
  const [open, setOpen] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (initialText !== undefined) setText(initialText);
  }, [initialText]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(Math.max(ta.scrollHeight, 24), 200)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) taRef.current?.focus();
  }, [autoFocus]);

  // Escritura global: si el usuario teclea sin foco en un input, redirige al textarea.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const ta = taRef.current;
      if (!ta || disabled) return;
      const active = document.activeElement as HTMLElement | null;
      const isEditable =
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          active.isContentEditable);
      if (isEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      // Solo caracteres imprimibles (incluye espacio); ignora teclas como Tab, Escape, flechas.
      if (e.key.length !== 1) return;
      ta.focus();
      // Dejamos que el evento se propague al textarea ya enfocado.
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [disabled]);

  function pickFile(f: File | null) {
    if (!f) {
      setFile(null);
      return;
    }
    if (!ACCEPTED.includes(f.type)) return;
    setFile(f);
  }

  function submit() {
    if (disabled || !text.trim()) return;
    onSend(text, file);
    setText("");
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  const canSend = !!text.trim() && !disabled;

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) pickFile(f);
      }}
      className={cn(
        "glass relative flex w-full flex-col gap-2 rounded-[28px] px-2.5 py-2.5 transition-all duration-200",
        dragOver && "ring-2 ring-primary/40"
      )}
    >
      {file && (
        <div className="mx-1.5 flex items-center gap-2 rounded-2xl bg-foreground/5 px-3 py-2">
          {file.type === "application/pdf" ? (
            <FileText className="h-4 w-4 text-primary-ink dark:text-primary" />
          ) : (
            <ImageIcon className="h-4 w-4 text-primary-ink dark:text-primary" />
          )}
          <span className="line-clamp-1 flex-1 text-sm">{file.name}</span>
          <button
            type="button"
            onClick={() => pickFile(null)}
            aria-label="Quitar adjunto"
            className="hover-surface grid h-6 w-6 place-items-center rounded-full text-muted-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="flex items-end gap-1.5">
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
        />
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Adjuntar"
              title="Adjuntar PDF o imágenes (PNG, JPG, WEBP)"
              className="hover-surface mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted-foreground"
            >
              <Plus className="h-[18px] w-[18px]" strokeWidth={2.2} />
            </button>
          </PopoverTrigger>
          <PopoverContent side="top" align="start" className="w-72 p-3">
            <div className="mb-2">
              <p className="text-sm font-medium text-primary-ink dark:text-primary">Adjuntar archivo</p>
              <p className="text-xs text-muted-foreground">PDF, PNG, JPG, WEBP · máx 20MB</p>
            </div>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setPopoverDragOver(true);
              }}
              onDragLeave={() => setPopoverDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setPopoverDragOver(false);
                const f = e.dataTransfer.files?.[0];
                if (f) {
                  pickFile(f);
                  setOpen(false);
                }
              }}
              onClick={() => fileRef.current?.click()}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-border/70 bg-foreground/5 px-3 py-5 text-center transition-colors hover:bg-foreground/10",
                popoverDragOver && "border-primary bg-primary/10"
              )}
            >
              <Upload className="h-5 w-5 text-muted-foreground" />
              <p className="text-sm">Arrastra aquí o <span className="text-primary-ink dark:text-primary">selecciona</span></p>
              <p className="text-[11px] text-muted-foreground">Acepta varios formatos a la vez</p>
            </div>
          </PopoverContent>
        </Popover>

        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          rows={1}
          className="block max-h-[200px] flex-1 resize-none border-0 bg-transparent px-1 py-2 text-[0.98rem] leading-relaxed placeholder:text-muted-foreground/70 focus:outline-none"
        />

        <button
          type="button"
          onClick={submit}
          disabled={!canSend}
          aria-label="Enviar"
          className={cn(
            "mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full transition-all duration-200",
            canSend
              ? "bg-primary text-primary-ink shadow-[0_4px_14px_-4px_hsl(var(--primary)/0.6)] hover:bg-primary-strong hover:scale-105 dark:text-primary-foreground"
              : "bg-foreground/10 text-foreground/30"
          )}
        >
          <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.4} />
        </button>
      </div>
    </div>
  );
}
