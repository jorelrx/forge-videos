import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Dashboard, DashboardView } from "./dashboard";
import type { DashboardState } from "../hooks/use-dashboard";
import type { StudioEvent, RunStatus, StageName } from "../lib/contracts";
import type { StudioApi } from "../lib/api";

function nanoId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function utcNow() {
  const d = new Date();
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    second: d.getUTCSeconds(),
    microsecond: 0,
  };
}

function makeRun(status: RunStatus, progress = 0.13, stage: StageName | null = "pesquisa" as StageName) {
  const now = utcNow();
  return {
    run: {
      id: nanoId(),
      status,
      video_id: nanoId(),
      priority: 50,
      queue_position: 1,
      config_snapshot: {},
      workflow_version: 1,
      git_commit: "abc123",
      lease_owner: null,
      lease_expires_at: null,
      pause_requested_at: null,
      created_at: now,
      started_at: now,
      finished_at: null,
      failure_code: null,
      failure_message: null,
    },
    video: {
      id: nanoId(),
      tema: "O tédio como alarme",
      tese: null,
      created_at: now,
      updated_at: now,
    },
    progress,
    current_stage: stage,
  } as any;
}

function fullState(overrides: Partial<DashboardState> = {}): DashboardState {
  return {
    queue: [],
    runs: [],
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
    focusRun: null,
    ...overrides,
  } as DashboardState;
}

function makeEvent(id: number, kind: string, level?: string, message?: string): StudioEvent {
  return {
    id,
    kind,
    level: level ?? "info",
    message: message ?? "",
    created_at: "2026-09-14T00:00:00Z",
    run_id: null,
    stage_run_id: null,
    work_item_id: null,
    payload: {},
  };
}

describe("dashboard — comportamento completo (REAL)", () => {
  it("carrega a projeção real pela API injetada", async () => {
    const running = makeRun("running", 0.5, "pesquisa");
    const api: StudioApi = {
      getQueue: vi.fn().mockResolvedValue([running]),
      getRuns: vi.fn().mockResolvedValue({
        items: [running],
        total: 1,
        limit: 50,
        offset: 0,
      }),
      getRun: vi.fn().mockResolvedValue(running),
      getServices: vi.fn().mockResolvedValue({}),
      getEvents: vi.fn().mockResolvedValue({ items: [], next_before_id: null }),
      createVideo: vi.fn(),
      pauseRun: vi.fn(),
      resumeRun: vi.fn(),
      retryStage: vi.fn(),
    };

    render(<Dashboard api={api} />);

    await new Promise((r) => setTimeout(r, 100));
    const title = await screen.findByRole("heading", { name: "O tédio como alarme" });
    expect(title).not.toBeNull();
    expect(api.getQueue).toHaveBeenCalledOnce();
    expect(api.getRuns).toHaveBeenCalledWith(50, 0);
    expect(api.getServices).toHaveBeenCalledOnce();
  });

  it("renderiza primeira tela com título e sem run ativa", () => {
    const state = fullState({ focusRun: null, queue: [], runs: [] });
    render(<DashboardView state={state} />);

    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Produção");
    expect(screen.getByText("Fila, execução atual e histórico num único lugar")).not.toBeNull();
    expect(screen.getByText("Nenhuma run ativa.")).not.toBeNull();
    expect(screen.getByText("Nenhum vídeo aguardando")).not.toBeNull();
    expect(screen.getByText("Forge Studio")).not.toBeNull();
  });

  it("renderiza run ativa com status, progresso, etapa e aviso de pausa", async () => {
    const state = fullState({
      focusRun: makeRun("running", 0.42, "pesquisa" as StageName),
    });
    render(<DashboardView state={state} />);

    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Produção");
    expect(screen.getByText("O tédio como alarme")).not.toBeNull();
    const progressVals = screen.getAllByText("42%");
    expect(progressVals.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "Ⅱ Solicitar pausa" })).not.toBeNull();
  });

  it("renderiza serviços com estado e latência", () => {
    const state = fullState({
      services: {
        transcricao: { name: "transcricao", state: "healthy", message: "Operacional", latency_ms: 240 },
        modelagem: { name: "modelagem", state: "degraded", message: "Latência alta", latency_ms: 1800 },
        "lm-studio": { name: "lm-studio", state: "degraded", message: "ocupado", latency_ms: 900 },
      } as any,
    });
    render(<DashboardView state={state} />);

    expect(screen.getByText("transcricao")).not.toBeNull();
    expect(screen.getByText(/Operacional/)).not.toBeNull();
    expect(screen.getByText("240ms")).not.toBeNull();
    expect(screen.getByText("modelagem")).not.toBeNull();
    expect(screen.getByText(/Latência alta/)).not.toBeNull();
    expect(screen.getByText("1800ms")).not.toBeNull();
  });

  it("renderiza histórico com runs e progresso", () => {
    const r1 = makeRun("completed", 1.0, null);
    const r2 = makeRun("failed", 0.07, "montagem" as StageName);
    const state: DashboardState = {
      ...fullState({ focusRun: r1 }),
      runs: [
        { run: { ...r1.run, id: "run-1", status: "completed" }, video: { ...r1.video, id: "v1", tema: "Felicidade" }, progress: 1.0, current_stage: null } as any,
        { run: { ...r2.run, id: "run-2", status: "failed" }, video: { ...r2.video, id: "v2", tema: "Existencialismo" }, progress: 0.07, current_stage: "montagem" } as any,
      ],
    };
    render(<DashboardView state={state} />);

    const table = screen.getByRole("table");
    const tbody = table.querySelector("tbody");
    expect(tbody?.children.length).toBeGreaterThanOrEqual(2);

    const allText = table.textContent ?? "";
    expect(allText).toContain("completed");
    expect(allText).toContain("failed");
    expect(allText).toContain("Montagem");
  });

  it("renderiza log ao vivo com eventos e níveis", () => {
    const state = fullState({
      events: [
        makeEvent(1, "stage.started", undefined, "Iniciando pesquisa"),
        makeEvent(2, "item.succeeded", undefined, "Item concluído"),
        makeEvent(3, "item.failed", undefined, "Falha na API externa"),
      ],
    });
    render(<DashboardView state={state} />);

    expect(screen.getByText("Iniciando pesquisa")).not.toBeNull();
    expect(screen.getByText("Item concluído")).not.toBeNull();
    expect(screen.getByText("Falha na API externa")).not.toBeNull();
  });

  it("renderiza artefato com URL e tipo", () => {
    const state = fullState({
      focusRun: {
        ...makeRun("completed", 1.0, null),
        artifacts: [{
          id: "artifact-1",
          kind: "video",
          relative_path: "output.mp4",
          mime_type: "video/mp4",
        }],
      } as any,
    });
    render(<DashboardView state={state} />);
    expect(screen.getByText("output.mp4")).not.toBeNull();
    expect(screen.getByText("video/mp4")).not.toBeNull();
  });

  it("renderiza fila de vídeos aguardando", () => {
    const state = fullState({
      focusRun: null,
      queue: [
        { video: { tema: "Vídeo 1" }, run: { status: "queued" }, progress: 0 } as any,
        { video: { tema: "Vídeo 2" }, run: { status: "queued" }, progress: 0 } as any,
      ],
    });
    render(<DashboardView state={state} />);

    expect(screen.getByText("Vídeo 1")).not.toBeNull();
    expect(screen.getByText("Vídeo 2")).not.toBeNull();
    expect(screen.getAllByText(/#\d/).length).toBeGreaterThanOrEqual(2);
  });

  it("renderiza drawer de falha quando há erro", () => {
    const state = fullState({
      focusRun: makeRun("failed", 0.13, "pesquisa" as StageName),
      error: new Error("Falha na etapa de pesquisa"),
    });
    render(<DashboardView state={state} />);
    expect(screen.getByRole("alert")).not.toBeNull();
    expect(screen.getByText("Falha na etapa de pesquisa")).not.toBeNull();
  });

  it("não renderiza drawer quando erro é nulo", () => {
    const state = fullState({
      focusRun: makeRun("running"),
      error: null,
    });
    render(<DashboardView state={state} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("desabilita formulário durante loading", () => {
    const state = fullState({
      focusRun: makeRun("running"),
      loading: true,
    });
    render(<DashboardView state={state} />);
    const form = screen.getByTestId("new-video-form");
    const fieldset = form.querySelector("fieldset");
    expect(fieldset?.hasAttribute("disabled")).toBe(true);
  });

  it("renderiza pausa e retry para run em execução", () => {
    const state = fullState({
      focusRun: makeRun("running", 0.42, "pesquisa" as StageName),
      pause: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn().mockResolvedValue(undefined),
    });
    render(<DashboardView state={state} />);

    expect(screen.getByRole("button", { name: "Ⅱ Solicitar pausa" })).not.toBeNull();
    expect(screen.getByLabelText("Repetir etapa")).not.toBeNull();
  });

  it("renderiza retomar para run pausado", () => {
    const state = fullState({
      focusRun: makeRun("paused", 0.42, "pesquisa" as StageName),
      resume: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn().mockResolvedValue(undefined),
    });
    render(<DashboardView state={state} />);

    expect(screen.getByRole("button", { name: "▶ Retomar" })).not.toBeNull();
    expect(screen.getByLabelText("Repetir etapa")).not.toBeNull();
  });
});
