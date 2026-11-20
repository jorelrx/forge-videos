import React from "react";
import { RunSummary } from "../lib/contracts";
import { formatRelative } from "../lib/format";

export interface QueueProps {
  runs: RunSummary[];
  /** Fila completa (tela Fila) mostra também a tese de cada vídeo. */
  detailed?: boolean;
}

export function Queue({ runs, detailed = false }: QueueProps) {
  if (!runs || runs.length === 0) {
    return (
      <div className="empty-inline">
        <p className="empty-state">Nenhum vídeo aguardando</p>
        <small>O próximo vídeo enfileirado entra aqui e o worker o pega assim que ficar livre.</small>
      </div>
    );
  }
  return (
    <ol className={`queue-list${detailed ? " detailed" : ""}`} aria-label="Fila de vídeos">
      {runs.map((r, i) => {
        const priority = r.run?.priority;
        const queuedAt = formatRelative(r.run?.created_at);
        return (
          <li key={r.run?.id ?? i} className="qitem">
            <span className="qpos">#{i + 1}</span>
            <div className="qbody">
              <b>{r.video?.tema || "Sem tema"}</b>
              {detailed && r.video?.tese && <p className="qtese">{r.video.tese}</p>}
              <small>
                {priority != null ? `Prioridade ${priority}` : "Prioridade padrão"}
                {queuedAt !== "—" ? ` · enfileirado ${queuedAt}` : ""}
              </small>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
