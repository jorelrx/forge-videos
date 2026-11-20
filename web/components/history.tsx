import React from "react";
import { RunSummary } from "../lib/contracts";
import { formatDateTime, formatDuration, shortId } from "../lib/format";
import { stageStatus } from "../lib/stage-map";
import { RunStatusBadge } from "./status-badge";

export interface HistoryProps {
  runs: RunSummary[];
  selectedRunId?: string | null;
  onSelectRun?: (runId: string) => void;
}

function progressOf(r: RunSummary): number {
  return Math.round(Math.min(1, Math.max(0, r.progress ?? 0)) * 100);
}

/**
 * Duração da execução: fechada quando há `finished_at`, corrente enquanto a
 * run anda. Run parada sem `finished_at` (falha, pausa) não tem duração
 * confiável, e contar até agora inventaria um número que só cresce.
 */
function durationText(r: RunSummary): string {
  const started = r.run?.started_at;
  if (!started) return "—";
  if (r.run?.finished_at) return formatDuration(started, r.run.finished_at);
  return ["preparing", "running", "validating", "pausing"].includes(r.run?.status ?? "")
    ? formatDuration(started)
    : "—";
}

/** Tabela completa de execuções (tela Runs). */
export function History({ runs, selectedRunId, onSelectRun }: HistoryProps) {
  if (!runs || runs.length === 0) {
    return (
      <div className="empty-inline">
        <p className="empty-state">Nenhum run recente</p>
        <small>Cada vídeo enfileirado vira uma execução e fica registrado aqui.</small>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="history-table" aria-label="Histórico de runs">
        <thead>
          <tr>
            <th scope="col">Vídeo</th>
            <th scope="col">Status</th>
            <th scope="col">Etapa</th>
            <th scope="col" className="num">Progresso</th>
            <th scope="col">Início</th>
            <th scope="col" className="num">Duração</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const id = r.run?.id;
            const selected = selectedRunId != null && selectedRunId === id;
            const pct = progressOf(r);
            const started = r.run?.started_at;
            return (
              <tr key={id ?? "—"} className={selected ? "history-selected" : ""}>
                <td className="hist-name">
                  <button
                    className="history-select"
                    type="button"
                    aria-pressed={selected}
                    aria-label={`Abrir execução ${r.video?.tema || id || "desconhecida"}`}
                    onClick={() => id && onSelectRun?.(id)}
                  >
                    <span className="hist-tema">{r.video?.tema || "Sem tema"}</span>
                    <small className="hist-meta mono" title={id}>{shortId(id)}</small>
                  </button>
                </td>
                <td><RunStatusBadge status={r.run?.status} /></td>
                <td>{r.current_stage ? stageStatus(r.current_stage) : "—"}</td>
                <td className="num">
                  <span className="meter" aria-hidden="true">
                    <span style={{ transform: `scaleX(${pct / 100})` }} />
                  </span>
                  {r.progress ? `${pct}%` : "—"}
                </td>
                <td className="muted">{formatDateTime(started)}</td>
                <td className="num muted">{durationText(r)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Lista curta das últimas execuções (tela Produção). */
export function RecentRuns({
  runs,
  selectedRunId,
  onSelectRun,
  limit = 5,
}: HistoryProps & { limit?: number }) {
  const items = (runs ?? []).slice(0, limit);
  if (items.length === 0) {
    return <p className="empty-state">Nenhum run recente</p>;
  }
  return (
    <ul className="recent-list">
      {items.map((r) => {
        const id = r.run?.id;
        const selected = selectedRunId != null && selectedRunId === id;
        return (
          <li key={id ?? "—"}>
            <button
              type="button"
              className={`recent-item${selected ? " selected" : ""}`}
              aria-pressed={selected}
              onClick={() => id && onSelectRun?.(id)}
            >
              <span className="recent-tema">{r.video?.tema || "Sem tema"}</span>
              <span className="recent-meta">
                <RunStatusBadge status={r.run?.status} />
                <span className="muted">{r.progress ? `${progressOf(r)}%` : ""}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
