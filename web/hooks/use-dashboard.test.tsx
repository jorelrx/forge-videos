import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioApi } from "../lib/api";
import { useDashboard } from "./use-dashboard";

class FakeEventSource {
  static current: FakeEventSource | null = null;

  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(_url: string) {
    FakeEventSource.current = this;
  }

  close() {}

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

const run = {
  run: { id: "run-1", status: "running" },
  video: { id: "video-1", tema: "Tema real", tese: null },
  progress: 0.25,
  current_stage: "pesquisa",
} as any;

function makeApi(): StudioApi {
  return {
    getQueue: vi.fn().mockResolvedValue([run]),
    getRuns: vi.fn().mockResolvedValue({
      items: [run],
      total: 1,
      limit: 50,
      offset: 0,
    }),
    getRun: vi.fn().mockResolvedValue({ ...run, stages: {}, artifacts: [] }),
    getServices: vi.fn().mockResolvedValue({}),
    getEvents: vi.fn().mockResolvedValue({ items: [], next_before_id: null }),
    createVideo: vi.fn(),
    pauseRun: vi.fn(),
    resumeRun: vi.fn(),
    retryStage: vi.fn(),
  } as unknown as StudioApi;
}

describe("useDashboard", () => {
  afterEach(() => {
    FakeEventSource.current = null;
    vi.restoreAllMocks();
  });

  it("carrega projeção inicial e seleciona run ativa", async () => {
    const api = makeApi();
    const { result } = renderHook(() =>
      useDashboard(api, { EventSource: FakeEventSource as unknown as typeof EventSource }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.focusRun?.run.id).toBe("run-1");
    expect(result.current.queue).toEqual([run]);
    expect(api.getRun).toHaveBeenCalledWith("run-1");
  });

  it("consolida burst SSE em um refresh", async () => {
    const api = makeApi();
    const { result } = renderHook(() =>
      useDashboard(api, { EventSource: FakeEventSource as unknown as typeof EventSource }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      FakeEventSource.current?.emit({
        id: 1,
        run_id: "run-1",
        kind: "stage.progress",
        level: "info",
        message: "25%",
        payload: {},
        created_at: "2026-09-14T00:00:00Z",
      });
      FakeEventSource.current?.emit({
        id: 2,
        run_id: "run-1",
        kind: "stage.progress",
        level: "info",
        message: "26%",
        payload: {},
        created_at: "2026-09-14T00:00:01Z",
      });
    });

    await waitFor(() => expect(api.getQueue).toHaveBeenCalledTimes(2));
    expect(api.getRuns).toHaveBeenCalledTimes(2);
  });

  it("mantém último snapshot quando refresh falha", async () => {
    const api = makeApi();
    const { result } = renderHook(() => useDashboard(api));
    await waitFor(() => expect(result.current.loading).toBe(false));
    (api.getQueue as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("API indisponível"),
    );

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.queue).toEqual([run]);
    expect(result.current.error?.message).toBe("API indisponível");
  });

  it("mostra a run recém-enfileirada mesmo com GET /api/services pendente", async () => {
    // GET /api/services sonda ComfyUI/LM Studio com timeout de 2s cada: medido
    // em 3,1 s contra a API real, contra 64 ms de /api/queue. A projeção da
    // fila não pode ficar refém dessa sondagem.
    const api = makeApi();
    (api.getQueue as ReturnType<typeof vi.fn>).mockResolvedValueOnce([run]);
    (api.getServices as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<never>(() => {}),
    );
    const { result } = renderHook(() => useDashboard(api));
    await waitFor(() => expect(result.current.queue).toEqual([run]));

    const enqueued = {
      run: { id: "run-2", status: "queued" },
      video: { id: "video-2", tema: "Vídeo novo", tese: null },
      progress: 0,
      current_stage: null,
    } as any;
    (api.getQueue as ReturnType<typeof vi.fn>).mockResolvedValue([run, enqueued]);

    act(() => {
      void result.current.createVideo({
        tema: "Vídeo novo",
        tese: null,
        priority: 50,
        preset: "local-recomendado-v1",
      });
    });

    await waitFor(() => expect(result.current.queue).toHaveLength(2), { timeout: 2000 });
    expect(result.current.queue[1].video.tema).toBe("Vídeo novo");
  });

  it("não descarta fila e runs quando GET /api/services falha", async () => {
    const api = makeApi();
    (api.getServices as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("probe indisponível"),
    );
    const { result } = renderHook(() => useDashboard(api));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.queue).toEqual([run]);
    expect(result.current.runs).toEqual([run]);
    expect(result.current.error?.message).toBe("probe indisponível");
  });

  it("não liga loading no refresh disparado por evento SSE", async () => {
    const api = makeApi();
    (api.getServices as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<never>(() => {}),
    );
    const { result } = renderHook(() =>
      useDashboard(api, { EventSource: FakeEventSource as unknown as typeof EventSource }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      FakeEventSource.current?.emit({
        id: 7,
        run_id: "run-1",
        kind: "stage.progress",
        level: "info",
        message: "50%",
        payload: {},
        created_at: "2026-09-14T00:00:02Z",
      });
    });

    await waitFor(() => expect(api.getQueue).toHaveBeenCalledTimes(2));
    expect(result.current.loading).toBe(false);
  });
});
