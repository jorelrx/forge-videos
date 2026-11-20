import React from "react";
import { RunSummary } from "../lib/contracts";
import { stageStatus } from "../lib/stage-map";

export interface HistoryProps {
  runs: RunSummary[];
  selectedRunId?: string | null;
  onSelectRun?: (runId: string) => void;
}

export function History({ runs, selectedRunId, onSelectRun }: HistoryProps) {
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
            <tr key={r.run?.id ?? "—"} className={selectedRunId === r.run?.id ? "history-selected" : ""}>
              <td className="hist-name"><button className="history-select" type="button" aria-pressed={selectedRunId === r.run?.id} aria-label={`Ver saídas da execução ${r.run?.id ?? "desconhecida"}`} onClick={() => r.run?.id && onSelectRun?.(r.run.id)}><span>{r.run?.id ?? "—"}</span><br /><small className="hist-meta">{selectedRunId === r.run?.id ? "selecionada" : `run ${r.run?.id?.slice(0, 8) ?? "—"}`}</small></button></td>
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
