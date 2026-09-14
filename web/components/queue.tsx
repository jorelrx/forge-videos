import React from "react";
import { RunSummary } from "../lib/contracts";

export interface QueueProps {
  runs: RunSummary[];
}

export function Queue({ runs }: QueueProps) {
  if (!runs || runs.length === 0) return <p className="empty-state">Nenhum vídeo aguardando</p>;
  return (
    <div className="queue-list" aria-label="Fila de vídeos">
      {runs.map((r, i) => (
        <div key={r.run?.id ?? i} className="qitem">
          <div className="qitem-top">
            <b>{r.video?.tema || "Sem tema"}</b>
            <span className="qpos">#{i + 1}</span>
          </div>
          <small>modo local · prioridade normal · ~42 min</small>
        </div>
      ))}
    </div>
  );
}
