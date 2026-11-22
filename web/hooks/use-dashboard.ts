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
  selectedRunId: string | null;
  selectRun(id: string): Promise<void>;
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
  escolherProposta?(input: import("../lib/contracts").EscolhaEditorial): Promise<void>;
  decidirConflitoPauta?(input: import("../lib/contracts").DecisaoConflitoPauta): Promise<void>;
  decidirAbertura?(input: import("../lib/contracts").DecisaoAbertura): Promise<void>;
}

export function useDashboard(
  api: StudioApi,
  dependencies: { EventSource?: typeof EventSource } = {},
): DashboardState {
  const { connection, events } = useStudioEvents(null, dependencies);
  const [queue, setQueue] = useState<RunSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [focusRun, setFocusRun] = useState<RunView | null>(null);
  const [selectedRunIdState, setSelectedRunIdState] = useState<string | null>(null);
  const selectedRunId = useRef<string | null>(null);
  const [services, setServices] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const servicesFailed = useRef(false);

  const captureFailure = useCallback((reason: unknown) => {
    setError(
      reason instanceof Error
        ? reason
        : new Error("Falha desconhecida ao atualizar o dashboard"),
    );
  }, []);

  /**
   * `silent` evita marcar loading em recargas disparadas por evento SSE: com
   * loading ligado o formulário de novo vídeo fica desabilitado durante cada
   * recarga, e a pipeline emite eventos o tempo todo.
   */
  const load = useCallback(
    async (silent: boolean) => {
      if (!silent) setLoading(true);
      try {
        // GET /api/services sonda ComfyUI/LM Studio com timeout de 2 s cada
        // (medido: ~3,1 s contra a API real, contra ~65 ms de /api/queue). A
        // fila não pode esperar por ela: o vídeo recém-enfileirado precisa
        // aparecer na hora, e uma sondagem pendente nunca deve travar a
        // projeção.
        void api.getServices().then(
          (value) => {
            servicesFailed.current = false;
            setServices(value);
          },
          (reason) => {
            servicesFailed.current = true;
            captureFailure(reason);
          },
        );

        const [queueResult, runsResult] = await Promise.allSettled([
          api.getQueue(),
          api.getRuns(50, 0),
        ]);

        let failure: unknown = null;
        if (queueResult.status === "fulfilled") {
          setQueue(queueResult.value);
        } else {
          failure ??= queueResult.reason;
        }

        if (runsResult.status === "fulfilled") {
          const page = runsResult.value;
          setRuns(page.items);
          const focus = selectedRunId.current
            ? { run: { id: selectedRunId.current } }
            : page.items.find((item) =>
                ["preparing", "running", "pausing", "validating"].includes(item.run.status),
              ) ??
              page.items.find((item) =>
                ["paused", "failed", "interrupted"].includes(item.run.status),
              ) ??
              page.items[0] ??
              null;
          if (focus) {
            try {
              const detail = await api.getRun(focus.run.id);
              selectedRunId.current = detail.run.id;
              setSelectedRunIdState(detail.run.id);
              setFocusRun(detail);
            } catch (reason) {
              if (!selectedRunId.current) setFocusRun(null);
              failure ??= reason;
            }
          } else if (!selectedRunId.current) {
            setFocusRun(null);
          }
        } else {
          failure ??= runsResult.reason;
        }

        if (failure) {
          captureFailure(failure);
        } else if (!servicesFailed.current) {
          setError(null);
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [api, captureFailure],
  );

  const refresh = useCallback(() => load(false), [load]);

  const selectRun = useCallback(async (id: string) => {
    selectedRunId.current = id;
    setSelectedRunIdState(id);
    setFocusRun(null);
    setError(null);
    try {
      const detail = await api.getRun(id);
      setFocusRun(detail);
    } catch (reason) {
      captureFailure(reason);
    }
  }, [api, captureFailure]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (events.length === 0) return;
    const timer = window.setTimeout(() => {
      void load(true);
    }, 100);
    return () => window.clearTimeout(timer);
  }, [events, load]);

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
    selectedRunId: selectedRunIdState,
    selectRun,
    services,
    events,
    connection,
    loading,
    error,
    refresh,
    async createVideo(input: CreateVideoRequest) {
      setLoading(true);
      try {
        const criada = await api.createVideo(input);
        if (input.revisao_editorial && typeof criada.run.id === "string") {
          selectedRunId.current = criada.run.id;
        }
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
    escolherProposta: api.escolherProposta && (async (input) => {
      if (!focusRun) return;
      await api.escolherProposta?.(focusRun.run.id, input);
      await refresh();
    }),
    decidirAbertura: api.decidirAbertura && (async (input) => {
      if (!focusRun) return;
      await api.decidirAbertura?.(focusRun.run.id, input);
      await refresh();
    }),
    decidirConflitoPauta: api.decidirConflitoPauta && (async (input) => {
      if (!focusRun) return;
      await api.decidirConflitoPauta?.(focusRun.run.id, input);
      await refresh();
    }),
  };
}
