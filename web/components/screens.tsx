import React from "react";
import type { RunSummary, ServiceHealth } from "../lib/contracts";
import { History } from "./history";
import { IconPlus } from "./icons";
import { screenIcon } from "./screen-meta";
import type { Screen } from "../hooks/use-screen";
import { Queue } from "./queue";
import { StatusBadge, runTone, serviceStateLabel, serviceTone } from "./status-badge";

export function PageHeader({
  screen,
  title,
  description,
  actions,
}: {
  screen: Screen;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  const Icon = screenIcon(screen);
  return (
    <header className="page-header" data-screen={screen}>
      <div className="page-title">
        <span className="page-icon" aria-hidden="true">
          <Icon size={20} />
        </span>
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>
      {actions && <div className="head-actions">{actions}</div>}
    </header>
  );
}

const SERVICE_NAMES: Record<string, string> = {
  worker: "Worker",
  research: "Acervo",
  lm_studio: "LM Studio",
  comfyui: "ComfyUI",
  tts: "TTS",
  ffmpeg: "FFmpeg",
  gpu: "Slot de GPU",
  codex: "Codex",
  claude: "Claude",
  anthropic: "Anthropic",
  openai: "OpenAI",
  youtube: "YouTube",
};

const SERVICE_ROLES: Record<string, string> = {
  worker: "Executa a fila de produção",
  research: "Passagens citáveis para pesquisa e roteiro",
  lm_studio: "Modelo local de texto",
  comfyui: "Geração de imagens",
  tts: "Síntese da narração",
  ffmpeg: "Montagem e codificação do vídeo",
  gpu: "Um consumidor residente por vez",
  codex: "Texto ou imagens pela assinatura ChatGPT",
  claude: "Modelo de texto pela assinatura Claude",
  anthropic: "Modelo de texto pela API Anthropic",
  openai: "Modelo de texto pela API OpenAI",
  youtube: "Publicação dos vídeos",
};

export function serviceName(key: string): string {
  return SERVICE_NAMES[key] ?? key;
}

/** Serviços que disputam a GPU; o broker mantém um residente por vez. */
export const GPU_SERVICES = ["lm_studio", "comfyui", "tts"];

/**
 * Texto do slot de GPU a partir de `/api/services`. O backend (saude.py)
 * responde "Residente: <consumidor>", "Sem residente" ou, com estado
 * `degraded`, "Estado ilegível"; só o primeiro caso ocupa o slot.
 */
export function gpuSlotLabel(services: Record<string, ServiceHealth>): string | null {
  const gpu = services["gpu"];
  if (gpu?.message?.startsWith("Residente")) return gpu.message;
  return null;
}

export function QueueScreen({ queue, onNewVideo }: { queue: RunSummary[]; onNewVideo: () => void }) {
  return (
    <main className="main">
      <PageHeader
        screen="fila"
        title="Fila"
        description="Vídeos esperando o worker, na ordem em que serão produzidos."
      />
      <section className="panel" aria-label="Fila de vídeos">
        <div className="panel-heading">
          <h3>Aguardando</h3>
          <span>{queue.length} {queue.length === 1 ? "vídeo" : "vídeos"}</span>
        </div>
        <Queue runs={queue} detailed />
        {queue.length === 0 && (
          <div className="panel-foot">
            <button className="btn btn-primary" type="button" onClick={onNewVideo}>
              <IconPlus size={14} />
              Novo vídeo
            </button>
          </div>
        )}
      </section>
    </main>
  );
}

const RUN_FILTERS: { id: string; label: string; match: (s: string) => boolean }[] = [
  { id: "todas", label: "Todas", match: () => true },
  { id: "ativas", label: "Em andamento", match: (s) => runTone(s) === "live" || runTone(s) === "warn" },
  { id: "concluidas", label: "Concluídas", match: (s) => s === "completed" },
  { id: "falhas", label: "Com falha", match: (s) => runTone(s) === "fail" },
];

export function RunsScreen({
  runs,
  selectedRunId,
  onOpenRun,
}: {
  runs: RunSummary[];
  selectedRunId: string | null;
  onOpenRun: (id: string) => void;
}) {
  const [filter, setFilter] = React.useState("todas");
  const active = RUN_FILTERS.find((f) => f.id === filter) ?? RUN_FILTERS[0];
  const visible = runs.filter((r) => active.match(r.run?.status ?? ""));

  return (
    <main className="main">
      <PageHeader
        screen="runs"
        title="Execuções"
        description="Todos os vídeos que passaram pelo worker. Abra um para ver etapas, saídas e ações."
      />
      <section className="panel" aria-label="Histórico de runs">
        <div className="panel-heading">
          <div className="segmented" role="group" aria-label="Filtrar execuções">
            {RUN_FILTERS.map((f) => {
              const count = runs.filter((r) => f.match(r.run?.status ?? "")).length;
              return (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={filter === f.id}
                  onClick={() => setFilter(f.id)}
                >
                  {f.label}
                  <span className="seg-count">{count}</span>
                </button>
              );
            })}
          </div>
          <span className="nowrap">{visible.length} de {runs.length}</span>
        </div>
        <History runs={visible} selectedRunId={selectedRunId} onSelectRun={onOpenRun} />
      </section>
    </main>
  );
}

export function ServicesScreen({ services }: { services: Record<string, ServiceHealth> }) {
  // O slot de GPU tem quadro próprio acima; na tabela ficam só os serviços.
  // Habilitados primeiro (ordem estável da API); depois os fora de uso.
  const all = Object.entries(services).filter(([key]) => key !== "gpu");
  const enabled = all.filter(([, s]) => s.enabled !== false);
  const disabled = all.filter(([, s]) => s.enabled === false);
  const entries = [...enabled, ...disabled];
  const gpuState = services["gpu"];
  const hasLatency = entries.some(([, s]) => s.latency_ms != null);
  const okCount = enabled.filter(([, s]) => serviceTone(s.state) === "ok").length;
  const slot = gpuSlotLabel(services);
  const summary =
    `${okCount} de ${enabled.length} habilitados disponíveis` +
    (disabled.length > 0 ? ` · ${disabled.length} fora de uso` : "");

  return (
    <main className="main">
      <PageHeader
        screen="servicos"
        title="Serviços"
        description="Tudo o que o Forge pode usar: o que a configuração atual habilita e se cada serviço responde."
      />

      <section className="panel gpu-slot" aria-label="Slot de GPU">
        <div>
          <h3>GPU</h3>
          <p>
            O broker mantém um único consumidor residente (LLM, TTS ou imagens) e troca por fase,
            nunca por item.
          </p>
        </div>
        <StatusBadge tone={slot ? "live" : gpuState?.state === "degraded" ? "warn" : "neutral"}>
          {slot ?? (gpuState?.state === "degraded" ? gpuState.message || "Estado ilegível" : "Livre")}
        </StatusBadge>
      </section>

      <section className="panel" aria-label="Estado dos serviços">
        <div className="panel-heading">
          <h3>Estado</h3>
          <span>{entries.length === 0 ? "sem dados" : summary}</span>
        </div>
        {entries.length === 0 ? (
          <div className="empty-inline">
            <p className="empty-state">Sem leitura dos serviços</p>
            <small>A sondagem leva alguns segundos; se a API estiver fora do ar, nada aparece aqui.</small>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="history-table services-table">
              <thead>
                <tr>
                  <th scope="col">Serviço</th>
                  <th scope="col">Uso</th>
                  <th scope="col">Disponibilidade</th>
                  <th scope="col">Detalhe</th>
                  {hasLatency && <th scope="col" className="num">Latência</th>}
                </tr>
              </thead>
              <tbody>
                {entries.map(([key, svc]) => (
                  <tr key={key} className={svc.enabled === false ? "svc-off" : undefined}>
                    <td>
                      <span className="svc-name">{serviceName(key)}</span>
                      <small className="hist-meta">{SERVICE_ROLES[key] ?? key}</small>
                    </td>
                    <td>
                      {svc.enabled === false ? (
                        <StatusBadge tone="neutral">Fora de uso</StatusBadge>
                      ) : (
                        <>
                          <StatusBadge tone="live">Habilitado</StatusBadge>
                          {svc.usos && svc.usos.length > 0 && (
                            <small className="hist-meta">{svc.usos.join(" · ")}</small>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      <StatusBadge tone={serviceTone(svc.state)}>{serviceStateLabel(svc.state)}</StatusBadge>
                    </td>
                    <td className="muted">{svc.message && svc.message !== "OK" ? svc.message : "—"}</td>
                    {hasLatency && (
                      <td className="num mono">{svc.latency_ms != null ? `${svc.latency_ms}ms` : "—"}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
