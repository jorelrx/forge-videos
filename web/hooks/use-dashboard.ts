import { useState, useEffect, useCallback, useRef } from "react";
import { useStudioEvents } from "./use-studio-events";
import type { StudioEvent, StudioEventsState } from "./use-studio-events";

export interface DashboardState {
  queue: any[];
  runs: any[];
  focusRun: any | null;
  services: Record<string, any>;
  events: StudioEvent[];
  connection: StudioEventsState["connection"];
  loading: boolean;
  error: any | null;
  refresh(): Promise<void>;
  createVideo(input: any): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  retry(stage: string): Promise<void>;
}

export interface StudioApi {
  getQueue(): Promise<any[]>;
  getRuns(limit?: number, offset?: number): Promise<{ items: any[]; total: number; limit: number; offset: number }>;
  getRun(id: string): Promise<any>;
  getServices(): Promise<Record<string, any>>;
  getEvents?(id: string, beforeId?: number): Promise<any>;
  createVideo(input: any): Promise<any>;
  pauseRun(id: string, key: string): Promise<any>;
  resumeRun(id: string, key: string): Promise<any>;
  retryStage(id: string, stage: string, key: string): Promise<any>;
}

export function useDashboard(
  api: StudioApi,
  dependencies: { EventSource?: typeof EventSource } = {},
): DashboardState {
  const { connection, events } = useStudioEvents(null, dependencies);
  const [queue, setQueue] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [focusRun, setFocusRun] = useState<any | null>(null);
  const [services, setServices] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<any | null>(null);

  const captureFailure = useCallback((reason: unknown) => {
    setError(reason);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextQueue, page, nextServices] = await Promise.all([
        api.getQueue(),
        api.getRuns(50, 0),
        api.getServices(),
      ]);
      const focus = page.items.find((item: any) =>
        ["preparing", "running", "pausing", "validating"].includes(item.run?.status),
      ) ?? page.items.find((item: any) =>
        ["paused", "failed", "interrupted"].includes(item.run?.status),
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
    async (command: (runId: string, key: string) => Promise<any>) => {
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
    async createVideo(input: any) {
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
    retry: (stage: string) => runCommand((runId: string, key: string) => api.retryStage(runId, stage, key)),
  };
}
