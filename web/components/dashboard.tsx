import React from "react";
import { NewVideoForm } from "./new-video-form";
import { ActiveRun } from "./active-run";
import { Queue } from "./queue";
import { RunProgress } from "./run-progress";
import { RunActions } from "./run-actions";
import { ServiceStrip } from "./service-strip";
import { LiveLog } from "./live-log";
import { History } from "./history";
import { ArtifactPreview } from "./artifact-preview";
import { FailureDrawer } from "./failure-drawer";
import type { DashboardState } from "../hooks/use-dashboard";

export interface DashboardProps {
  api?: any;
  eventSource?: typeof EventSource;
}

export interface DashboardViewProps {
  state: DashboardState;
}

export function DashboardView({ state }: DashboardViewProps) {
  return (
    <main className="dashboard">
      <h1>Forge Video Studio</h1>
      <section aria-label="Título e identificação" className="dashboard-title">
        <h2>Observabilidade — Dashboard</h2>
      </section>
      <ServiceStrip services={state.services || {}} />
      <NewVideoForm onSubmit={state.createVideo} disabled={state.loading} />
      {state.focusRun ? (
        <section aria-label="Run ativa" className="active-run-section">
          <ActiveRun
            run={state.focusRun}
            onPause={state.pause}
            onResume={state.resume}
            onRetry={state.retry}
            disabled={state.loading}
          />
          <RunProgress currentStage={state.focusRun.current_stage} progress={state.focusRun.progress} />
          <RunActions
            run={{ status: state.focusRun.run?.status || "queued" }}
            onPause={state.pause}
            onResume={state.resume}
            onRetry={state.retry}
            disabled={state.loading}
          />
        </section>
      ) : (
        <p>Nenhuma run ativa.</p>
      )}
      <ArtifactPreview artifact={state.focusRun?.artifact} />
      <Queue runs={state.queue} />
      <History runs={state.runs || []} />
      <LiveLog events={state.events || []} />
      <FailureDrawer error={state.error} open={!!state.error} />
    </main>
  );
}

export function Dashboard({ api, eventSource }: DashboardProps) {
  const state = {
    queue: [],
    runs: [],
    focusRun: null,
    services: {},
    events: [],
    connection: "offline" as const,
    loading: false,
    error: null,
    refresh: async () => {},
    createVideo: async () => {},
    pause: async () => {},
    resume: async () => {},
    retry: async () => {},
  };
  return <DashboardView state={state} />;
}
