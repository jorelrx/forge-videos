import React from "react";
import type { StudioEvent, StudioEventsState } from "../hooks/use-studio-events";
import { IconAlert, IconRefresh } from "./icons";

const CONNECTION_TEXT: Record<StudioEventsState["connection"], string> = {
  connecting: "Conectando…",
  live: "Ao vivo",
  reconnecting: "Reconectando…",
  offline: "Desconectado",
};

function levelClass(level: string): string {
  if (level === "error") return "log-err";
  if (level === "warn" || level === "warning") return "log-warn";
  if (level === "ok" || level === "success") return "log-ok";
  return "";
}

function eventTime(event: StudioEvent): string {
  // created_at vem em ISO-8601 UTC; o relógio do operador é o local.
  const date = typeof event.created_at === "string" ? new Date(event.created_at) : null;
  if (!date || Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * Painel de atividade: o fluxo SSE do worker e, quando a projeção falha, o
 * aviso com a ação de recarregar. Rola sozinho para o fim enquanto o operador
 * já estiver no fim; se ele subiu para ler, a rolagem fica onde está.
 */
export function ActivityDock({
  events,
  connection,
  error,
  onRetry,
}: {
  events: StudioEvent[];
  connection: StudioEventsState["connection"];
  error?: Error | null;
  onRetry?: () => void;
}) {
  const logRef = React.useRef<HTMLDivElement>(null);
  const stickToEnd = React.useRef(true);
  const visible = events.slice(-120);

  React.useEffect(() => {
    const el = logRef.current;
    if (el && stickToEnd.current) el.scrollTop = el.scrollHeight;
  }, [events]);

  return (
    <aside className="dock" aria-label="Atividade">
      <header className="dock-head">
        <h2>Atividade</h2>
        <span className={`conn-pill conn-${connection}`}>
          <span className="conn-dot" aria-hidden="true" />
          {CONNECTION_TEXT[connection]}
        </span>
      </header>

      {error != null && (
        <div className="dock-alert" role="alert" aria-label="Falhas recentes">
          <IconAlert size={16} />
          <div>
            <b>{error.message || "Falha desconhecida"}</b>
            <p>Os dados na tela podem estar desatualizados. O que já foi produzido continua salvo.</p>
            {onRetry && (
              <button className="btn btn-sm" data-choice="retry-failed" type="button" onClick={onRetry}>
                <IconRefresh size={14} />
                Recarregar
              </button>
            )}
          </div>
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
            Nenhum evento ainda. O progresso de pesquisa, áudio, imagens e montagem aparece aqui
            enquanto o worker trabalha.
          </p>
        ) : (
          visible.map((e) => (
            <div key={e.id} className={`log-line ${levelClass(e.level)}`}>
              <time className="log-time">{eventTime(e)}</time>
              <span className="log-kind">{e.kind}</span>
              <span className="log-msg">{e.message || "—"}</span>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
