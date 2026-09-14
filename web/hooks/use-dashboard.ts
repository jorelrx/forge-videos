import { useState, useEffect, useCallback, useRef } from "react";
import { useStudioEvents } from "./use-studio-events";
import type { StudioEvent, StudioEventsState } from "./use-studio-events";
import type { StudioApi } from "../lib/api";
import type {
  CreateVideoRequest,
  RunSummary,
  RunView,
  ServiceHealth,
  StageName,
} from "../lib/contracts";

export interface DashboardState {
  queue: RunSummary[];
  runs: RunSummary[];
  focusRun: RunView | null;
  services: Record<string, ServiceHealth>;
  events: StudioEvent[];
  connection: StudioEventsState["connection"];
  loading: boolean;
  error: Error | null;
  refresh(): Promise<void>;
  createVideo(input: CreateVideoRequest): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  retry(stage: StageName): Promise<void>;
}

export function useDashboard(
  api: StudioApi,
  dependencies: { EventSource?: typeof EventSource } = {},
): DashboardState {
  const { connection, events } = useStudioEvents(null, dependencies);
  const [queue, setQueue] = useState<RunSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [focusRun, setFocusRun] = useState<RunView | null>(null);
  const [services, setServices] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const captureFailure = useCallback((reason: unknown) => {
    setError(
      reason instanceof Error
        ? reason
        : new Error("Falha desconhecida ao atualizar o dashboard"),
    );
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextQueue, page, nextServices] = await Promise.all([
        api.getQueue(),
        api.getRuns(50, 0),
        api.getServices(),
      ]);
      const focus = page.items.find((item) =>
        ["preparing", "running", "pausing", "validating"].includes(item.run.status),
      ) ?? page.items.find((item) =>
        ["paused", "failed", "interrupted"].includes(item.run.status),
      ) ?? null;
      const nextFocus = focus ? await api.getRun(focus.run.id) : null;
      setQueue(nextQueue);
      setRuns(page.items);
      setFocusRun(nextFocus);
      setServices(nextServices);
      setError(null);
    } catch (reason) {
      captureFailure(reason);
    } finally {
      setLoading(false);
    }
  }, [api, captureFailure]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (events.length === 0) return;
    const timer = window.setTimeout(() => {
      void refresh();
    }, 100);
    return () => window.clearTimeout(timer);
  }, [events, refresh]);

  const runCommand = useCallback(
    async (command: (runId: string, key: string) => Promise<unknown>) => {
      if (!focusRun) {
        captureFailure(new Error("Nenhuma run selecionada"));
        return;
      }
      setLoading(true);
      try {
        await command(focusRun.run.id, crypto.randomUUID());
        await refresh();
      } catch (reason) {
        captureFailure(reason);
      } finally {
        setLoading(false);
      }
    },
    [captureFailure, focusRun, refresh],
  );

  return {
    queue,
    runs,
    focusRun,
    services,
    events,
    connection,
    loading,
    error,
    refresh,
    async createVideo(input: CreateVideoRequest) {
      setLoading(true);
      try {
        await api.createVideo(input);
        await refresh();
      } catch (reason) {
        captureFailure(reason);
      } finally {
        setLoading(false);
      }
    },
    pause: () => runCommand((runId: string, key: string) => api.pauseRun(runId, key)),
    resume: () => runCommand((runId: string, key: string) => api.resumeRun(runId, key)),
    retry: (stage: StageName) => runCommand((runId, key) => api.retryStage(runId, stage, key)),
  };
}
