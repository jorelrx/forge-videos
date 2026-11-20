import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
        lm_studio: { name: "lm_studio", state: "degraded", message: "ocupado", latency_ms: 900 },
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

  it("marca GPU pelos nomes reais do backend (underscore)", () => {
    const state = fullState({
      services: {
        lm_studio: { name: "lm_studio", state: "degraded", message: "ocupado", latency_ms: 900 },
        comfyui: { name: "comfyui", state: "healthy", message: "", latency_ms: 20 },
        tts: { name: "tts", state: "healthy", message: "", latency_ms: 30 },
      } as any,
    });
    render(<DashboardView state={state} />);

    const lmChip = screen.getByText("lm_studio").closest(".service-chip");
    const comfyChip = screen.getByText("comfyui").closest(".service-chip");
    const ttsChip = screen.getByText("tts").closest(".service-chip");
    expect(lmChip?.classList.contains("gpu")).toBe(true);
    expect(comfyChip?.classList.contains("gpu")).toBe(true);
    expect(ttsChip?.classList.contains("gpu")).toBe(true);
    expect(screen.getByText(/GPU · LLM · ocupado/)).not.toBeNull();
  });

  it("header 'Novo vídeo' foca o formulário e não cria vídeo vazio", async () => {
    const createVideo = vi.fn().mockResolvedValue(undefined);
    const state = fullState({
      focusRun: null,
      createVideo: createVideo as any,
    });
    const user = userEvent.setup();
    render(<DashboardView state={state} />);

    await user.click(screen.getByRole("button", { name: "Novo vídeo" }));

    expect(createVideo).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText("Tema"));
  });

  it("mostra a etapa real do pipeline (sem '—' fixo)", () => {
    const state = fullState({
      focusRun: makeRun("running", 0.42, "roteiro" as StageName),
    });
    render(<DashboardView state={state} />);

    const pipeline = screen.getByLabelText("Pipeline de etapas");
    const stages = Array.from(pipeline.querySelectorAll(".stage small"));
    expect(stages.length).toBeGreaterThanOrEqual(6);
    for (const el of stages) {
      expect(el.textContent).not.toContain("—");
    }
    expect(pipeline.textContent).toContain("fonte citável");
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

  it("renderiza player da saída selecionada, sem miniatura fictícia", async () => {
    const user = userEvent.setup();
    const focusRun = makeRun("completed", 1.0, null) as any;
    const state = fullState({
      focusRun: {
        ...focusRun,
        artifacts: [{
          id: "artifact-1", run_id: focusRun.run.id, stage_run_id: "stage-1",
          work_item_id: null, kind: "video/final.mp4", relative_path: "video/final.mp4",
          mime_type: "video/mp4", size_bytes: 1024, sha256: "a".repeat(64),
          metadata: {}, is_current: true, created_at: "2026-10-01T00:00:00Z",
        }],
      } as any,
    });
    const { container } = render(<DashboardView state={state} />);
    await user.click(screen.getByRole("tab", { name: /Vídeo/ }));
    expect(container.querySelector("video")?.getAttribute("src")).toContain("artifact-1");
    expect(screen.getByText(/^final\.mp4 · 0 MB\./)).not.toBeNull();
    expect(screen.queryByLabelText("Artefato mais recente")).toBeNull();
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

  it("renderiza pausa e retry para run em execução", async () => {
    const state = fullState({
      focusRun: makeRun("running", 0.42, "pesquisa" as StageName),
      pause: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn().mockResolvedValue(undefined),
    });
    render(<DashboardView state={state} />);

    expect(screen.getByRole("button", { name: "Ⅱ Solicitar pausa" })).not.toBeNull();
    // A API recusa retry fora de paused/failed/completed com 409
    // ({"detail": {"error": {"code": "transition_invalid", "message":
    // "run: running -> queued"}}), então a etapa só é oferecida quando é aceita.
    expect(screen.queryByLabelText("Repetir etapa")).toBeNull();
  });

  it("oferece retry somente quando a API aceita (paused/failed/completed)", () => {
    for (const status of ["paused", "failed", "completed"] as const) {
      const { unmount } = render(
        <DashboardView
          state={fullState({
            focusRun: makeRun(status, 0.42, "pesquisa" as StageName),
            retry: vi.fn().mockResolvedValue(undefined),
          })}
        />,
      );
      expect(screen.getByLabelText("Repetir etapa"), `status=${status}`).not.toBeNull();
      unmount();
    }
    for (const status of ["running", "preparing", "validating"] as const) {
      const { unmount } = render(
        <DashboardView
          state={fullState({
            focusRun: makeRun(status, 0.42, "pesquisa" as StageName),
            retry: vi.fn().mockResolvedValue(undefined),
          })}
        />,
      );
      expect(screen.queryByLabelText("Repetir etapa"), `status=${status}`).toBeNull();
      unmount();
    }
  });

  it("não oferece 'Retomar' enquanto a pausa está em andamento", () => {
    // Capturado: POST .../resume com a run em `pausing` responde 409
    // {"detail": {"error": {"code": "transition_invalid", "message": "run: pausing -> queued"}}}.
    const state = fullState({
      focusRun: makeRun("pausing", 0.42, "pesquisa" as StageName),
      resume: vi.fn().mockResolvedValue(undefined),
    });
    render(<DashboardView state={state} />);

    expect(screen.queryByRole("button", { name: "▶ Retomar" })).toBeNull();
  });

  it("marca a etapa pelo status real da API, não pela posição do chip", () => {
    // Ordem canônica do domínio (GET /api/runs/{id} devolve as 8 etapas nessa
    // ordem): preparacao, pesquisa, roteiro, plano_midia, audio, imagens,
    // montagem, validacao. Na run real, `audio` executa antes de `imagens`.
    const focusRun = {
      ...makeRun("running", 0.5, "audio" as StageName),
      stages: {
        preparacao: { stage_run: { status: "succeeded" } },
        pesquisa: { stage_run: { status: "succeeded" } },
        roteiro: { stage_run: { status: "succeeded" } },
        plano_midia: { stage_run: { status: "succeeded" } },
        audio: { stage_run: { status: "running" } },
        imagens: { stage_run: { status: "pending" } },
        montagem: { stage_run: { status: "pending" } },
        validacao: { stage_run: { status: "pending" } },
      },
    } as any;
    render(<DashboardView state={fullState({ focusRun })} />);

    const pipeline = screen.getByLabelText("Pipeline de etapas");
    const chips = Array.from(pipeline.querySelectorAll(".stage"));
    const chip = (label: string) =>
      chips.find((c) => c.querySelector("b")?.textContent === label);

    expect(chip("Áudio")?.className).toContain("live");
    expect(chip("Imagens")?.className).toContain("wait");
    expect(chip("Imagens")?.className).not.toContain("ok");
    expect(chip("Pesquisa")?.className).toContain("ok");
  });

  it("marca a etapa corrente em preparacao/plano_midia sem mentir sobre as demais", () => {
    const focusRun = {
      ...makeRun("running", 0.13, "plano_midia" as StageName),
      stages: {
        preparacao: { stage_run: { status: "succeeded" } },
        pesquisa: { stage_run: { status: "succeeded" } },
        roteiro: { stage_run: { status: "succeeded" } },
        plano_midia: { stage_run: { status: "running" } },
        audio: { stage_run: { status: "pending" } },
        imagens: { stage_run: { status: "pending" } },
        montagem: { stage_run: { status: "pending" } },
        validacao: { stage_run: { status: "pending" } },
      },
    } as any;
    render(<DashboardView state={fullState({ focusRun })} />);

    const chips = Array.from(
      screen.getByLabelText("Pipeline de etapas").querySelectorAll(".stage"),
    );
    const chip = (label: string) =>
      chips.find((c) => c.querySelector("b")?.textContent === label);

    // Nenhum chip representa plano_midia, mas nada depois dele pode aparecer ok.
    expect(chip("Pesquisa")?.className).toContain("ok");
    expect(chip("Roteiro")?.className).toContain("ok");
    for (const label of ["Áudio", "Imagens", "Montagem", "Validação"]) {
      expect(chip(label)?.className, label).toContain("wait");
    }
  });

  it("botão '＋ Novo vídeo' da barra lateral foca o formulário", async () => {
    const createVideo = vi.fn();
    const state = fullState({ focusRun: null, createVideo: createVideo as any });
    const user = userEvent.setup();
    const { container } = render(<DashboardView state={state} />);

    const sidebarButton = container.querySelector(
      '[data-choice="new-run"]',
    ) as HTMLButtonElement;
    expect(sidebarButton).not.toBeNull();
    await user.click(sidebarButton);

    expect(createVideo).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText("Tema"));
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

  it("navega para a aba Publicação com a run concluída mais recente e volta", async () => {
    const done = makeRun("completed", 1, null);
    done.run.finished_at = "2026-11-02T10:00:00Z";
    const loadArtifacts = vi.fn().mockResolvedValue([]);
    const state = fullState({ runs: [done] });
    const user = userEvent.setup();
    render(<DashboardView state={state} loadArtifacts={loadArtifacts} />);

    const nav = screen.getByRole("button", { name: /Publicação/ });
    await user.click(nav);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Publicação");
    expect(nav.getAttribute("aria-current")).toBe("page");
    expect(await screen.findByText("Embalagem ausente")).not.toBeNull();
    expect(loadArtifacts).toHaveBeenCalledWith(done.run.id);

    await user.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Produção");
  });

  it("'＋ Novo vídeo' na aba Publicação volta à produção e foca o formulário", async () => {
    const state = fullState({ runs: [] });
    const user = userEvent.setup();
    const { container } = render(<DashboardView state={state} loadArtifacts={async () => []} />);

    await user.click(screen.getByRole("button", { name: /Publicação/ }));
    await user.click(container.querySelector('[data-choice="new-run"]') as HTMLButtonElement);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Produção");
    expect(document.activeElement).toBe(screen.getByLabelText("Tema"));
  });
});
