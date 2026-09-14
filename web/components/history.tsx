import React from "react";
import { RunSummary } from "../lib/contracts";

export interface HistoryProps {
  runs: RunSummary[];
}

export function History({ runs }: HistoryProps) {
  return (
    <section aria-label="Histórico de runs" className="history">
      <h3>Histórico</h3>
      <table>
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
          {runs.map((r) => (
            <tr key={r.run.id}>
              <td>{r.run.id}</td>
              <td>{r.video?.tema || "—"}</td>
              <td>{r.run.status}</td>
              <td>{Math.round((r.progress || 0) * 100)}%</td>
              <td>{r.current_stage || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
