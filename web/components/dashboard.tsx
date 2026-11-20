"use client";

import React from "react";
import { NewVideoForm } from "./new-video-form";
import { ActiveRun } from "./active-run";
import { Queue } from "./queue";
import { History } from "./history";
import { RunOutputs } from "./run-outputs";
import { Publication } from "./publication";
import { useDashboard, type DashboardState } from "../hooks/use-dashboard";
import { createStudioApi, type StudioApi } from "../lib/api";
import type { Artifact, StudioEvent, StageName } from "../lib/contracts";
import { serviceStatusLabel, stageStatus } from "../lib/stage-map";

export interface DashboardProps {
  api?: StudioApi;
  eventSource?: typeof EventSource;
}

export interface DashboardViewProps {
  state: DashboardState;
  /** Injetável para teste; padrão é `GET /api/runs/{id}/artifacts`. */
  loadArtifacts?: (runId: string) => Promise<Artifact[]>;
}

type DashboardScreen = "dashboard" | "publicacao";

const defaultApi = createStudioApi();

const SIDEBAR_NAV = [
  { id: "nav-dashboard", label: "Dashboard", ico: "◫", default: true },
  { id: "nav-queue", label: "Fila", ico: "≡" },
  { id: "nav-runs", label: "Runs", ico: "◷" },
  { id: "nav-publicacao", label: "Publicação", ico: "⇪" },
  { id: "nav-services", label: "Serviços", ico: "⌁" },
  { id: "nav-config", label: "Configuração", ico: "⚙" },
] as const;

/**
 * Ordem canônica do domínio (forge.domain.operacao.StageName / ETAPAS): é a
 * ordem em que o worker executa e em que `GET /api/runs/{id}` devolve `stages`.
 * `audio` roda antes de `imagens` (o broker encerra o ComfyUI antes do TTS).
 */
const STAGE_ORDER: StageName[] = [
  "preparacao",
  "pesquisa",
  "roteiro",
  "plano_midia",
  "audio",
  "imagens",
  "montagem",
  "validacao",
];

const PIPELINE_STAGES: { key: StageName; label: string; sub: string }[] = [
  { key: "pesquisa", label: "Pesquisa", sub: "fonte citável" },
  { key: "roteiro", label: "Roteiro", sub: "9 seções · score" },
  { key: "audio", label: "Áudio", sub: "blocos · f0" },
  { key: "imagens", label: "Imagens", sub: "beats · passos" },
  { key: "montagem", label: "Montagem", sub: "trilhas · duração" },
  { key: "validacao", label: "Validação", sub: "codecs · frames" },
];

type ChipStatus = "ok" | "live" | "wait" | "fail";

/**
 * Status do chip a partir do `stage_run.status` real da API. O índice na ordem
 * canônica é só fallback para quando a projeção não traz `stages`: por posição,
 * a etapa `imagens` aparecia como concluída enquanto `audio` executava, e uma
 * run em `preparacao`/`plano_midia` não mostrava nenhuma etapa ativa.
 */
function pipelineChipStatus(
  stage: StageName,
  stageStatusValue: string | undefined,
  currentStage: StageName | null,
): ChipStatus {
  switch (stageStatusValue) {
    case "succeeded":
      return "ok";
    case "failed":
    case "interrupted":
      return "fail";
    case "running":
    case "pausing":
    case "paused":
      return "live";
    case "pending":
    case "invalidated":
      return "wait";
  }
  const currentIdx = currentStage ? STAGE_ORDER.indexOf(currentStage) : -1;
  const idx = STAGE_ORDER.indexOf(stage);
  if (currentIdx < 0 || idx < 0) return "wait";
  if (idx === currentIdx) return "live";
  return idx < currentIdx ? "ok" : "wait";
}

interface PipelineStageProps {
  stage: StageName;
  status: "ok" | "live" | "wait" | "fail";
  sub: string;
  num: number;
  items?: string;
}

function PipelineStage({ stage, status, sub, num, items }: PipelineStageProps) {
  return (
    <div className={`stage ${status}`}>
      <div className="stage-topline">
        <span className="stage-num">{String(num).padStart(2, "0")}</span>
        <span className="statusdot" aria-hidden="true" />
      </div>
      <b>{stageStatus(stage)}</b>
      <small>
        {sub}
        {items ? ` · ${items}` : ""}
      </small>
    </div>
  );
}

function ServiceStripItem({
  name,
  state,
  message,
  latencyMs,
  isGpu,
}: {
  name: string;
  state: string;
  message?: string;
  latencyMs?: number | null;
  isGpu?: boolean;
}) {
  const ledState =
    state === "available" || state === "healthy"
      ? "led"
      : state === "degraded"
        ? "led busy"
        : "led off";
  return (
    <div className={`service-chip ${isGpu ? "gpu" : ""}`}>
      <span className={ledState} aria-hidden="true" />
      <span>{name}</span>
      {message && <span style={{ color: "var(--muted)" }}>· {message}</span>}
      {latencyMs != null && <span>{latencyMs}ms</span>}
    </div>
  );
}

/** Itens da navegação que trocam de tela; os demais ainda são só rótulo. */
const NAV_SCREENS: Partial<Record<string, DashboardScreen>> = {
  "nav-dashboard": "dashboard",
  "nav-publicacao": "publicacao",
};

function Sidebar({
  queueCount,
  onNewRun,
  screen,
  onNavigate,
}: {
  queueCount: number;
  onNewRun: () => void;
  screen: DashboardScreen;
  onNavigate: (screen: DashboardScreen) => void;
}) {
  return (
    <aside className="sidebar" aria-label="Navegação">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">F</div>
        Forge Studio
      </div>

      <button
        className="sidebar-btn"
        data-choice="new-run"
        type="button"
        onClick={onNewRun}
      >
        ＋ Novo vídeo
      </button>

      <div className="section-label">Operação</div>
      {SIDEBAR_NAV.map((item) => {
        const target = NAV_SCREENS[item.id];
        const isActive = target === screen;
        const navigate = () => { if (target) onNavigate(target); };
        return (
          <div
            key={item.id}
            className={`nav-item ${isActive ? "active" : ""}`}
            role="button"
            tabIndex={0}
            aria-current={isActive ? "page" : undefined}
            onClick={navigate}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                navigate();
              }
            }}
          >
            <span className="nav-ico">{item.ico}</span>
            {item.label}
            {item.id === "nav-queue" && queueCount > 0 && (
              <span className="nav-count">{queueCount}</span>
            )}
          </div>
        );
      })}

      <div className="section-label">Sistema</div>
      <div className="nav-item" role="button" tabIndex={0}>
        <span className="nav-ico">⌁</span> Serviços
      </div>
      <div className="nav-item" role="button" tabIndex={0}>
        <span className="nav-ico">⚙</span> Configuração
      </div>

      <div className="sidebar-mini">
        <b>V1 · operação local</b>
        <br />
        Um worker · um consumidor GPU por vez
      </div>
    </aside>
  );
}

function Dock({ events, error }: {
  events: StudioEvent[];
  error?: Error | null;
}) {
  const hasFailures = error != null;

  return (
    <aside className="dock" aria-label="Painel lateral">
      <div>
        <h2>Log ao vivo</h2>
        <div className="dock-sub">Áudio · atualização há 2s</div>
      </div>

      <div className="log-view" aria-label="Registros ao vivo">
        {events.length === 0 ? (
          <div className="log-line" style={{ color: "var(--muted)" }}>
            Aguardando eventos…
          </div>
        ) : (
          events.slice(-30).map((e) => (
            <div key={e.id} className={`log-line log-${e.level === "error" ? "err" : e.level === "warn" ? "warn" : e.level === "ok" ? "ok" : ""}`}>
              <span className="log-time">{e.created_at ? e.created_at.slice(11, 19) : "—"}</span>
              <span style={{ color: "#506176" }}>[{e.kind}]</span>
              <span>{e.message || "—"}</span>
            </div>
          ))
        )}
      </div>

      {hasFailures && (
        <div className="failure-box" role="alert" aria-label="Falhas recentes">
          <b>{error!.message || "Falha desconhecida"}</b>
          <p>
            O run pode concluir parcialmente. Falhas permanecem visíveis no manifesto.
          </p>
          <button className="retry-btn" data-choice="retry-failed" type="button">
            Repetir somente os falhos
          </button>
        </div>
      )}
    </aside>
  );
}

export function DashboardView({ state, loadArtifacts }: DashboardViewProps) {
  const focusRun = state.focusRun;
  const formRef = React.useRef<HTMLFormElement>(null);
  const [screen, setScreen] = React.useState<DashboardScreen>("dashboard");
  const [focusFormPending, setFocusFormPending] = React.useState(false);
  const services = state.services ?? {};
  const events = state.events ?? [];
  const queue = state.queue ?? [];
  const runs = state.runs ?? [];
  const loading = state.loading;
  const error = state.error;

  const focusStatus = focusRun?.run?.status ?? "queued";
  // Mesmas regras de run-actions.tsx, que espelham o ControlPlane: retry_stage
  // só é aceito a partir de paused/failed/completed e resume a partir de
  // paused/failed/interrupted (fora disso a API responde 409
  // "transition_invalid"). Oferecer o que a API recusa faz o clique não
  // acontecer do ponto de vista do operador.
  const canPauseRun = ["preparing", "running", "validating"].includes(focusStatus);
  const canResumeRun = ["paused", "failed", "interrupted"].includes(focusStatus);
  const canRetryRun = ["paused", "failed", "completed"].includes(focusStatus);

  const queueItemCount = queue.length;

  const activePipeline: {
    stage: StageName;
    status: "ok" | "live" | "wait" | "fail";
    sub: string;
    items?: string;
  }[] = [];
  if (focusRun) {
    for (const s of PIPELINE_STAGES) {
      const stageView = focusRun.stages?.[s.key];
      const status = pipelineChipStatus(
        s.key,
        stageView?.stage_run?.status,
        focusRun.current_stage ?? null,
      );

      let items = "";
      if (stageView) {
        const cur = stageView.stage_run?.current_items;
        const tot = stageView.stage_run?.total_items;
        if (cur != null && tot != null && tot > 0) {
          items = `${cur}/${tot}`;
        }
      }

      activePipeline.push({ stage: s.key, status, sub: s.sub, items });
    }
  }

  const gpuSvc = services["gpu"];
  const gpuConsumer = services["lm_studio"] || services["comfyui"] || services["tts"];
  const gpuResident = gpuSvc?.message?.startsWith("Residente") ?? false;
  const gpuLabel = gpuResident ? gpuSvc!.message : gpuConsumer?.message ?? "GPU livre";
  const gpuActive = gpuConsumer?.state === "degraded" || gpuResident;

  const serviceList = Object.entries(services).map(([name, svc]) => ({
    name,
    state: svc.state ?? "unknown",
    message: svc.message,
    latencyMs: svc.latency_ms ?? null,
    isGpu: ["lm_studio", "comfyui", "tts"].includes(name),
  }));

  const sidebar = (
    <Sidebar
      queueCount={queueItemCount}
      onNewRun={requestNewVideo}
      screen={screen}
      onNavigate={setScreen}
    />
  );

  // O formulário só existe na tela de produção: vindo de outra tela, troca
  // primeiro e foca depois que ele montar.
  React.useEffect(() => {
    if (!focusFormPending || screen !== "dashboard") return;
    setFocusFormPending(false);
    const field = formRef.current?.querySelector<HTMLInputElement>("#tema")
      ?? document.getElementById("tema");
    field?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    field?.focus();
  }, [focusFormPending, screen]);

  function requestNewVideo() {
    if (screen === "dashboard") {
      focusNewVideoForm();
      return;
    }
    setScreen("dashboard");
    setFocusFormPending(true);
  }

  function focusNewVideoForm() {
    const form = formRef.current;
    const field =
      form?.querySelector<HTMLInputElement>("#tema") ??
      document.getElementById("tema");
    if (!field) return;
    field.scrollIntoView?.({ behavior: "smooth", block: "center" });
    field.focus();
  }

  const mainContent = (
    <main className="main">
      <div className="page-header">
        <div>
          <h1>Produção</h1>
          <p>Fila, execução atual e histórico num único lugar</p>
        </div>
        <div className="head-actions">
          <button className="btn" data-choice="open-folder" type="button">
            Abrir output
          </button>
          <button
            className="btn btn-primary"
            data-choice="new-run-top"
            type="button"
            onClick={focusNewVideoForm}
          >
            Novo vídeo
          </button>
        </div>
      </div>

      <div className="services-strip" aria-label="Status dos serviços">
        {serviceList.map((s) => (
          <ServiceStripItem key={s.name} {...s} />
        ))}
        {gpuActive && (
          <span className="service-chip gpu">
            <span className="led busy" aria-hidden="true" />
            GPU · LLM · {gpuLabel}
          </span>
        )}
      </div>

      <NewVideoForm
        ref={formRef}
        onSubmit={(input) => state.createVideo?.(input)}
        disabled={loading}
      />

      {focusRun ? (
        <section className="active-run-card" aria-label="Run ativa">
          <ActiveRun
            run={focusRun}
            statusLabel={serviceStatusLabel(focusStatus)}
            progressPercent={StateProgressPercent(focusRun.progress ?? 0)}
            onPause={state.pause}
            onResume={state.resume}
            onRetry={state.retry}
            disabled={loading}
          />

          <div className="progress-bar" aria-hidden="true">
            <div
              className="progress-bar-fill"
              style={{ width: `${Math.min(100, Math.max(0, (focusRun.progress ?? 0) * 100))}%` }}
            />
          </div>

          <div className="pipeline" aria-label="Pipeline de etapas">
            {activePipeline.map((p) => (
              <PipelineStage
                key={p.stage}
                stage={p.stage}
                status={p.status}
                sub={p.sub}
                num={PIPELINE_STAGES.findIndex((s) => s.key === p.stage) + 1}
                items={p.items}
              />
            ))}
          </div>

          <RunOutputs key={focusRun.run.id} run={focusRun} />

          <div className="run-actions">
            {focusStatus === "pausing" && (
              <span className="safe-note">Pausa aplicada após o bloco atual · zero artefato parcial</span>
            )}
            {state.pause && canPauseRun && (
              <button
                className="btn btn-warn"
                data-choice="pause"
                type="button"
                onClick={() => state.pause()}
                disabled={loading}
              >
                Ⅱ Solicitar pausa
              </button>
            )}
            {canResumeRun && state.resume && (
              <button
                className="btn"
                data-choice="resume"
                type="button"
                onClick={() => state.resume()}
                disabled={loading}
              >
                ▶ Retomar
              </button>
            )}
            {state.retry && canRetryRun && (
              <select
                className="retry-select"
                aria-label="Repetir etapa"
                value=""
                onChange={(e) => {
                  const val = e.target.value as StageName | "";
                  if (val) state.retry(val);
                }}
              >
                <option value="">Repetir etapa…</option>
                {PIPELINE_STAGES.map((s) => (
                  <option key={s.key} value={s.key}>
                    {stageStatus(s.key)}
                  </option>
                ))}
              </select>
            )}
          </div>
        </section>
      ) : (
        <p className="empty-state">{state.selectedRunId
          ? error ? "A execução selecionada não pôde ser carregada." : "Abrindo execução selecionada…"
          : "Nenhuma run ativa."}</p>
      )}

      <div className="columns">
        <section className="panel queue-list-panel" aria-label="Fila de vídeos">
          <div className="panel-heading">
            <h3>Fila de vídeos</h3>
            <span>{queue.length} aguardando</span>
          </div>
          <Queue runs={queue} />
        </section>

        <section className="panel" aria-label="Histórico de runs">
          <div className="panel-heading">
            <h3>Runs recentes</h3>
            <span>Ver todos →</span>
          </div>
          <History runs={runs} selectedRunId={state.selectedRunId} onSelectRun={state.selectRun} />
        </section>
      </div>
    </main>
  );

  const dockContent = (
    <Dock
      events={events}
      error={error}
    />
  );

  return (
    <div className="app">
      {sidebar}
      {screen === "publicacao"
        ? <Publication runs={runs} loadArtifacts={loadArtifacts} />
        : mainContent}
      {dockContent}
    </div>
  );
}

function StateProgressPercent(progress: number): number {
  return Math.round(Math.min(1, Math.max(0, progress)) * 100);
}

export function Dashboard({ api, eventSource }: DashboardProps) {
  const state = useDashboard(api ?? defaultApi, {
    EventSource: eventSource,
  });
  return <DashboardView state={state} />;
}
