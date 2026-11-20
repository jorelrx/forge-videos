"use client";

import React from "react";
import { NewVideoForm } from "./new-video-form";
import { ActiveRun, lastStageWithData } from "./active-run";
import { ActivityDock } from "./activity-dock";
import { Queue } from "./queue";
import { RecentRuns } from "./history";
import { RunOutputs } from "./run-outputs";
import { Publication } from "./publication";
import { Sidebar } from "./sidebar";
import {
  GPU_SERVICES,
  PageHeader,
  QueueScreen,
  RunsScreen,
  ServicesScreen,
  gpuSlotLabel,
  serviceName,
} from "./screens";
import {
  IconAlert,
  IconArrowRight,
  IconHistory,
  IconPause,
  IconPlay,
  IconPlus,
  IconQueue,
  IconRefresh,
} from "./icons";
import { runTone, serviceTone } from "./status-badge";
import { useDashboard, type DashboardState } from "../hooks/use-dashboard";
import { screenHref, useScreen } from "../hooks/use-screen";
import { createStudioApi, type StudioApi } from "../lib/api";
import type { Artifact, ServiceHealth, StageName } from "../lib/contracts";
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

const defaultApi = createStudioApi();

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

const PIPELINE_STAGES: { key: StageName; sub: string }[] = [
  { key: "pesquisa", sub: "fontes do acervo" },
  { key: "roteiro", sub: "9 seções revisadas" },
  { key: "audio", sub: "narração por bloco" },
  { key: "imagens", sub: "uma por cena" },
  { key: "montagem", sub: "trilha e legendas" },
  { key: "validacao", sub: "codecs e duração" },
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

const CHIP_STATUS_TEXT: Record<ChipStatus, string> = {
  ok: "concluída",
  live: "em andamento",
  wait: "aguardando",
  fail: "falhou",
};

function PipelineStage({
  stage,
  status,
  sub,
  num,
  items,
}: {
  stage: StageName;
  status: ChipStatus;
  sub: string;
  num: number;
  items?: string;
}) {
  return (
    <li
      className={`stage ${status}`}
      data-stage={stage}
      aria-current={status === "live" ? "step" : undefined}
    >
      <div className="stage-topline">
        <span className="stage-num">{String(num).padStart(2, "0")}</span>
        <span className="statusdot" aria-hidden="true" />
        <span className="sr-only">{CHIP_STATUS_TEXT[status]}</span>
      </div>
      <b>{stageStatus(stage)}</b>
      <small>
        {sub}
        {items ? ` · ${items}` : ""}
      </small>
    </li>
  );
}

/**
 * Faixa compacta de serviços na Produção: nome e estado. A mensagem só
 * aparece quando o serviço não está disponível; latência e detalhes ficam na
 * tela Serviços.
 */
function ServicesStrip({
  services,
  onOpen,
}: {
  services: Record<string, ServiceHealth>;
  onOpen: () => void;
}) {
  const entries = Object.entries(services).filter(([key]) => key !== "gpu");
  const slot = gpuSlotLabel(services);
  if (entries.length === 0 && !slot) return null;
  return (
    <div className="services-strip" aria-label="Status dos serviços">
      {entries.map(([key, svc]) => {
        const tone = serviceTone(svc.state);
        return (
          <span
            key={key}
            className={`service-chip tone-${tone}${GPU_SERVICES.includes(key) ? " gpu" : ""}`}
            title={svc.message || undefined}
          >
            <span className="led" aria-hidden="true" />
            <span>{serviceName(key)}</span>
            {tone !== "ok" && svc.message && <span className="chip-msg">· {svc.message}</span>}
          </span>
        );
      })}
      {slot && (
        <span className="service-chip slot">
          <span className="led" aria-hidden="true" />
          GPU · {slot}
        </span>
      )}
      <a
        className="strip-link"
        href={screenHref("servicos")}
        onClick={(event) => {
          event.preventDefault();
          onOpen();
        }}
      >
        Detalhes
      </a>
    </div>
  );
}

export function DashboardView({ state, loadArtifacts }: DashboardViewProps) {
  const focusRun = state.focusRun;
  const formRef = React.useRef<HTMLFormElement>(null);
  const [screen, navigate] = useScreen();
  const [focusFormPending, setFocusFormPending] = React.useState(false);
  const services = state.services ?? {};
  const events = state.events ?? [];
  const queue = state.queue ?? [];
  const runs = state.runs ?? [];
  const loading = state.loading;
  const error = state.error;
  const connection = state.connection ?? "offline";

  const focusStatus = focusRun?.run?.status ?? "queued";
  // Mesmas regras de run-actions.tsx, que espelham o ControlPlane: retry_stage
  // só é aceito a partir de paused/failed/completed e resume a partir de
  // paused/failed/interrupted (fora disso a API responde 409
  // "transition_invalid"). Oferecer o que a API recusa faz o clique não
  // acontecer do ponto de vista do operador.
  const canPauseRun = ["preparing", "running", "validating"].includes(focusStatus);
  const canResumeRun = ["paused", "failed", "interrupted"].includes(focusStatus);
  const canRetryRun = ["paused", "failed", "completed"].includes(focusStatus);

  const activePipeline: { stage: StageName; status: ChipStatus; sub: string; items?: string }[] = [];
  if (focusRun) {
    for (const s of PIPELINE_STAGES) {
      const stageView = focusRun.stages?.[s.key];
      const status = pipelineChipStatus(
        s.key,
        stageView?.stage_run?.status,
        focusRun.current_stage ?? null,
      );
      const cur = stageView?.stage_run?.current_items;
      const tot = stageView?.stage_run?.total_items;
      const items = cur != null && tot != null && tot > 0 ? `${cur}/${tot}` : "";
      activePipeline.push({ stage: s.key, status, sub: s.sub, items });
    }
  }

  // O formulário só existe na tela de produção: vindo de outra tela, troca
  // primeiro e foca depois que ele montar.
  React.useEffect(() => {
    if (!focusFormPending || screen !== "producao") return;
    setFocusFormPending(false);
    focusNewVideoForm();
  }, [focusFormPending, screen]);

  function requestNewVideo() {
    if (screen === "producao") {
      focusNewVideoForm();
      return;
    }
    navigate("producao");
    setFocusFormPending(true);
  }

  function focusNewVideoForm() {
    const field =
      formRef.current?.querySelector<HTMLInputElement>("#tema") ??
      document.getElementById("tema");
    if (!field) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    field.scrollIntoView?.({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    field.focus();
  }

  function openRun(id: string) {
    void state.selectRun?.(id);
    navigate("producao");
  }

  const progressPct = progressPercent(focusRun?.progress ?? 0);
  const failureMessage = focusRun?.run?.failure_message;
  const failureCode = focusRun?.run?.failure_code;
  const showActions = focusStatus === "pausing" || canPauseRun || canResumeRun || canRetryRun;

  const production = (
    <main className="main">
      <PageHeader
        screen="producao"
        title="Produção"
        description="Acompanhe a execução em foco e enfileire o próximo vídeo."
      />

      <ServicesStrip services={services} onOpen={() => navigate("servicos")} />

      <div className="prod-grid">
        <div className="prod-primary">
          {focusRun ? (
            <>
              <section
                className={`panel active-run-card tone-${runTone(focusStatus)}`}
                data-stage={focusRun.current_stage ?? lastStageWithData(focusRun.stages) ?? undefined}
                aria-label="Execução em foco"
              >
                <ActiveRun
                  run={focusRun}
                  statusLabel={serviceStatusLabel(focusStatus)}
                  progressPercent={progressPct}
                />

                <div
                  className="progress-bar"
                  role="progressbar"
                  aria-label="Progresso da execução"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progressPct}
                >
                  {/* O preenchimento é o espectro das etapas inteiro, recortado até o
                      progresso: a cor na ponta diz em que trecho do pipeline a run está. */}
                  <div
                    className="progress-bar-fill"
                    style={{ clipPath: `inset(0 ${100 - progressPct}% 0 0 round 999px)` }}
                  />
                </div>

                <ol className="pipeline" aria-label="Pipeline de etapas">
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
                </ol>

                {failureMessage && (
                  <div className="run-failure">
                    <b>A execução parou</b>
                    <p>{failureMessage}</p>
                    {failureCode && <code>{failureCode}</code>}
                  </div>
                )}

                {showActions && (
                  <div className="run-actions">
                    {focusStatus === "pausing" && (
                      <span className="safe-note">
                        A pausa entra ao fim do bloco atual. Nenhum arquivo fica pela metade.
                      </span>
                    )}
                    {state.pause && canPauseRun && (
                      <button
                        className="btn"
                        data-choice="pause"
                        type="button"
                        onClick={() => state.pause()}
                        disabled={loading}
                      >
                        <IconPause size={14} />
                        Solicitar pausa
                      </button>
                    )}
                    {canResumeRun && state.resume && (
                      <button
                        className="btn btn-primary"
                        data-choice="resume"
                        type="button"
                        onClick={() => state.resume()}
                        disabled={loading}
                      >
                        <IconPlay size={14} />
                        Retomar
                      </button>
                    )}
                    {state.retry && canRetryRun && (
                      <select
                        className="select"
                        aria-label="Repetir etapa"
                        value=""
                        disabled={loading}
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
                )}
              </section>

              <RunOutputs key={focusRun.run.id} run={focusRun} />
            </>
          ) : (
            <section className="panel empty-hero" aria-label="Execução em foco">
              {state.selectedRunId ? (
                <p className="empty-state">
                  {error
                    ? "A execução selecionada não pôde ser carregada."
                    : "Abrindo execução selecionada…"}
                </p>
              ) : (
                <>
                  <h2>Nenhuma execução em andamento</h2>
                  <p>
                    Escreva um tema em <b>Novo vídeo</b>. O worker pesquisa o acervo, escreve o
                    roteiro, narra, gera as imagens e monta o vídeo; cada etapa aparece aqui.
                  </p>
                </>
              )}
            </section>
          )}
        </div>

        <div className="prod-side">
          <section className="panel" aria-labelledby="novo-video-title">
            <div className="panel-heading">
              <h3 id="novo-video-title" className="titled" data-screen="producao">
                <span className="title-icon" aria-hidden="true"><IconPlus size={14} /></span>
                Novo vídeo
              </h3>
            </div>
            <NewVideoForm
              ref={formRef}
              onSubmit={(input) => state.createVideo?.(input)}
              disabled={loading}
            />
          </section>

          <section className="panel queue-list-panel" aria-label="Fila de vídeos">
            <div className="panel-heading">
              <h3 className="titled" data-screen="fila">
                <span className="title-icon" aria-hidden="true"><IconQueue size={14} /></span>
                Fila
              </h3>
              <span>{queue.length} aguardando</span>
            </div>
            <Queue runs={queue} />
          </section>

          <section className="panel" aria-label="Runs recentes">
            <div className="panel-heading">
              <h3 className="titled" data-screen="runs">
                <span className="title-icon" aria-hidden="true"><IconHistory size={14} /></span>
                Recentes
              </h3>
              <a
                className="link"
                href={screenHref("runs")}
                onClick={(event) => {
                  event.preventDefault();
                  navigate("runs");
                }}
              >
                Ver todas
                <IconArrowRight size={13} />
              </a>
            </div>
            <RecentRuns runs={runs} selectedRunId={state.selectedRunId} onSelectRun={openRun} />
          </section>
        </div>
      </div>
    </main>
  );

  let content: React.ReactNode;
  switch (screen) {
    case "publicacao":
      content = <Publication runs={runs} loadArtifacts={loadArtifacts} />;
      break;
    case "fila":
      content = <QueueScreen queue={queue} onNewVideo={requestNewVideo} />;
      break;
    case "runs":
      content = (
        <RunsScreen runs={runs} selectedRunId={state.selectedRunId} onOpenRun={openRun} />
      );
      break;
    case "servicos":
      content = <ServicesScreen services={services} />;
      break;
    default:
      content = production;
  }

  const runLabels: Record<string, string> = {};
  for (const r of runs) {
    if (r.run?.id && r.video?.tema) runLabels[r.run.id] = r.video.tema;
  }

  return (
    <div className="app">
      <Sidebar
        screen={screen}
        onNavigate={navigate}
        onNewRun={requestNewVideo}
        queueCount={queue.length}
      />
      <div className="main-col">
        {error != null && (
          // Fica no topo de toda tela: em larguras menores o painel de
          // atividade desce para o fim da página e o aviso sumiria de vista.
          <div className="app-alert" role="alert" aria-label="Falhas recentes">
            <IconAlert size={16} />
            <div className="app-alert-body">
              <b>{error.message || "Falha desconhecida"}</b>
              <p>Os dados na tela podem estar desatualizados. O que já foi produzido continua salvo.</p>
            </div>
            {state.refresh && (
              <button className="btn btn-sm" data-choice="retry-failed" type="button" onClick={() => void state.refresh()}>
                <IconRefresh size={14} />
                Recarregar
              </button>
            )}
          </div>
        )}
        {content}
      </div>
      <ActivityDock
        events={events}
        connection={connection}
        runLabels={runLabels}
        focusRunId={focusRun?.run?.id ?? null}
      />
    </div>
  );
}

function progressPercent(progress: number): number {
  return Math.round(Math.min(1, Math.max(0, progress)) * 100);
}

export function Dashboard({ api, eventSource }: DashboardProps) {
  const state = useDashboard(api ?? defaultApi, {
    EventSource: eventSource,
  });
  return <DashboardView state={state} />;
}
