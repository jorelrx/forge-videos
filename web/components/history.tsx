import React from "react";
import { RunSummary } from "../lib/contracts";
import { stageStatus } from "../lib/stage-map";

export interface HistoryProps {
  runs: RunSummary[];
}

export function History({ runs }: HistoryProps) {
  if (!runs || runs.length === 0) return <p className="empty-state">Nenhum run recente</p>;

  return (
    <table className="history-table" aria-label="Histórico de runs">
      <thead>
        <tr>
          <th>Run</th>
          <th>Vídeo</th>
          <th>Status</th>
          <th>Progresso</th>
          <th>Etapa</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const status = r.run?.status ?? "—";
          const statusClass = status === "completed" ? "status-ok" : status === "failed" || status === "interrupted" ? "status-fail" : "";
          const stage = r.current_stage ? stageStatus(r.current_stage) : "—";
          const pct = Math.round((r.progress ?? 0) * 100);
          return (
            <tr key={r.run?.id ?? "—"}>
              <td className="hist-name"><div>{r.run?.id ?? "—"}<br /><small className="hist-meta">hoje · run {r.run?.id?.slice(0, 8) ?? "—"}</small></div></td>
              <td>{r.video?.tema || "—"}</td>
              <td className={statusClass}>{status}</td>
              <td>{pct === 0 && r.progress === 0 ? "—" : `${pct}%`}</td>
              <td>{stage}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
