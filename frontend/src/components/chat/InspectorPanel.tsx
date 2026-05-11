import { useState } from "react";
import { ChevronRight, FileSearch, Layers, Link2, ShieldAlert, X } from "lucide-react";
import type { Source, Trace } from "@/types/chat";
import { cn } from "@/lib/utils";

interface InspectorProps {
  trace: Trace | null;
  sources: Source[];
  onClose: () => void;
}

type Tab = "process" | "sources";

export function InspectorPanel({ trace, sources, onClose }: InspectorProps) {
  const [tab, setTab] = useState<Tab>("process");

  return (
    <aside className="glass animate-slide-right flex h-full w-[340px] flex-col rounded-[28px]">
      <div className="flex items-center gap-1 p-2 pl-3">
        <TabButton active={tab === "process"} onClick={() => setTab("process")} icon={<Layers className="h-3.5 w-3.5" />}>
          Proceso
        </TabButton>
        <TabButton active={tab === "sources"} onClick={() => setTab("sources")} icon={<FileSearch className="h-3.5 w-3.5" />}>
          Fuentes
        </TabButton>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="hover-surface ml-auto grid h-8 w-8 place-items-center rounded-full text-foreground/70"
        >
          <X className="h-[18px] w-[18px]" strokeWidth={2.2} />
        </button>
      </div>

      <div className="cg-scroll flex-1 overflow-y-auto px-5 pb-5">
        {tab === "process" ? <ProcessView trace={trace} /> : <SourcesView sources={sources} />}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  children,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
        active ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/5"
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function ProcessView({ trace }: { trace: Trace | null }) {
  if (!trace) {
    return <Empty title="Sin actividad" description="Aquí verás los pasos del pipeline tras tu primera consulta." />;
  }

  return (
    <div className="space-y-5 pt-2">
      <div>
        <p className="mb-1.5 text-[0.7rem] font-medium uppercase tracking-wider text-muted-foreground/80">
          Resumen
        </p>
        <p className="text-sm leading-relaxed">{trace.summary || "Sin resumen."}</p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Pill>historial {trace.history_turns ?? 0}</Pill>
        <Pill>recuperados {trace.retrieved_candidates ?? 0}</Pill>
        <Pill>seleccionados {trace.curated_candidates ?? 0}</Pill>
        {trace.safety_mode && (
          <Pill tone="warning">
            <ShieldAlert className="h-3 w-3" />
            modo cauto
          </Pill>
        )}
        {trace.active_document && <Pill>{trace.active_document}</Pill>}
      </div>

      {trace.steps && trace.steps.length > 0 && (
        <div>
          <p className="mb-2 text-[0.7rem] font-medium uppercase tracking-wider text-muted-foreground/80">
            Pasos
          </p>
          <ol className="space-y-2">
            {trace.steps.map((step, i) => (
              <li key={i} className="rounded-2xl bg-foreground/5 p-3">
                <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-foreground/10 text-[0.7rem]">
                    {i + 1}
                  </span>
                  {step.title || `Paso ${i + 1}`}
                </div>
                <p className="text-[0.82rem] leading-relaxed text-muted-foreground">
                  {step.detail}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function SourcesView({ sources }: { sources: Source[] }) {
  if (!sources.length) {
    return <Empty title="Sin fuentes" description="Las fuentes citadas aparecerán aquí." />;
  }

  return (
    <div className="space-y-2.5 pt-2">
      {sources.map((s, i) => {
        const title = (s.metadata?.title as string) || `Fuente ${i + 1}`;
        const url = s.metadata?.source_url as string | undefined;
        return (
          <article key={s.id || i} className="rounded-2xl bg-foreground/5 p-3">
            <div className="mb-1.5 flex items-start justify-between gap-3">
              <h3 className="text-sm font-medium leading-snug">{title}</h3>
              {typeof s.distance === "number" && (
                <span className="shrink-0 text-[0.7rem] text-muted-foreground/70">
                  d {s.distance.toFixed(3)}
                </span>
              )}
            </div>
            <p className="line-clamp-4 text-[0.82rem] leading-relaxed text-muted-foreground">
              {s.text}
            </p>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <Link2 className="h-3 w-3" />
                Abrir
                <ChevronRight className="h-3 w-3" />
              </a>
            )}
          </article>
        );
      })}
    </div>
  );
}

function Pill({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[0.7rem] font-medium",
        tone === "warning" ? "bg-destructive/10 text-destructive" : "bg-foreground/8 text-muted-foreground"
      )}
    >
      {children}
    </span>
  );
}

function Empty({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-[240px] text-xs leading-relaxed text-muted-foreground">{description}</p>
    </div>
  );
}
