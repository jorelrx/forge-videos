import React from "react";
import type { StudioEvent, StudioEventsState } from "../hooks/use-studio-events";
import { shortId } from "../lib/format";

const CONNECTION_TEXT: Record<StudioEventsState["connection"], string> = {
  connecting: "Conectando…",
  live: "Ao vivo",
  reconnecting: "Reconectando…",
  offline: "Desconectado",
};

type Scope = "foco" | "todas";

function levelClass(level: string): string {
  if (level === "error") return "log-err";
  if (level === "warn" || level === "warning") return "log-warn";
  if (level === "ok" || level === "success") return "log-ok";
  return "";
}

/** Hora local; eventos de outro dia levam a data junto, para não parecerem de agora. */
function eventTime(event: StudioEvent, today: string): string {
  const date = typeof event.created_at === "string" ? new Date(event.created_at) : null;
  if (!date || Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (date.toDateString() === today) return time;
  return `${date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${time}`;
}

/**
 * Painel de atividade: o fluxo SSE do worker, de todas as execuções. Cada
 * linha diz de qual execução veio, e o filtro "Em foco" deixa só a que está
 * aberta na Produção. Rola sozinho para o fim enquanto o operador já estiver
 * no fim; se ele subiu para ler, a rolagem fica onde está.
 */
export function ActivityDock({
  events,
  connection,
  runLabels = {},
  focusRunId = null,
}: {
  events: StudioEvent[];
  connection: StudioEventsState["connection"];
  /** run_id → tema, para identificar a origem de cada evento. */
  runLabels?: Record<string, string>;
  focusRunId?: string | null;
}) {
  const logRef = React.useRef<HTMLDivElement>(null);
  const stickToEnd = React.useRef(true);
  const [scope, setScope] = React.useState<Scope>("todas");
  const effectiveScope: Scope = focusRunId ? scope : "todas";
  const filtered =
    effectiveScope === "foco" ? events.filter((e) => e.run_id === focusRunId) : events;
  const visible = filtered.slice(-120);
  const today = new Date().toDateString();

  React.useEffect(() => {
    const el = logRef.current;
    if (el && stickToEnd.current) el.scrollTop = el.scrollHeight;
  }, [visible.length, effectiveScope]);

  return (
    <aside className="dock" aria-label="Atividade">
      <header className="dock-head">
        <h2>Atividade</h2>
        <span className={`conn-pill conn-${connection}`}>
          <span className="conn-dot" aria-hidden="true" />
          {CONNECTION_TEXT[connection]}
        </span>
      </header>

      {focusRunId && (
        <div className="segmented segmented-full" role="group" aria-label="Origem dos eventos">
          <button type="button" aria-pressed={effectiveScope === "todas"} onClick={() => setScope("todas")}>
            Todas as execuções
          </button>
          <button type="button" aria-pressed={effectiveScope === "foco"} onClick={() => setScope("foco")}>
            Em foco
          </button>
        </div>
      )}

      <div
        ref={logRef}
        className="log-view"
        role="log"
        aria-label="Registros ao vivo"
        // Região rolável: precisa de foco pelo teclado para rolar sem mouse.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        onScroll={(event) => {
          const el = event.currentTarget;
          stickToEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
      >
        {visible.length === 0 ? (
          <p className="log-empty">
            {effectiveScope === "foco"
              ? "Nenhum evento desta execução desde que o painel abriu."
              : "Nenhum evento ainda. O progresso de pesquisa, áudio, imagens e montagem aparece aqui enquanto o worker trabalha."}
          </p>
        ) : (
          visible.map((e) => {
            const origin = e.run_id ? runLabels[e.run_id] ?? shortId(e.run_id) : null;
            return (
              <div key={e.id} className={`log-line ${levelClass(e.level)}`}>
                <time className="log-time">{eventTime(e, today)}</time>
                <span className="log-kind">
                  {effectiveScope === "todas" && origin ? <span className="log-origin">{origin}</span> : null}
                  {e.kind}
                </span>
                <span className="log-msg">{e.message || "—"}</span>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
