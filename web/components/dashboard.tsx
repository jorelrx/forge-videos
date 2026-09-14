import React from "react";
import { NewVideoForm } from "./new-video-form";
import { ActiveRun } from "./active-run";
import { Queue } from "./queue";
import { RunProgress } from "./run-progress";
import { RunActions } from "./run-actions";
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
    <main>
      <h1>Forge Video Studio</h1>
      <NewVideoForm onSubmit={state.createVideo} disabled={state.loading} />
      {state.focusRun ? (
        <>
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
        </>
      ) : (
        <p>Nenhuma run ativa.</p>
      )}
      <Queue runs={state.queue} />
    </main>
  );
}

export function Dashboard({ api, eventSource }: DashboardProps) {
  // Minimal stub; real version uses useDashboard hook in full build
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
