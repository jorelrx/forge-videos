/**
 * Fluxo do painel contra os corpos reais da API: criar um vídeo pela UI,
 * ver o run recém-enfileirado na fila e acompanhar progresso ao vivo pelo SSE.
 *
 * Todos os corpos abaixo foram capturados por HTTP real (uvicorn + SQLite
 * temporário); ver o relatório da auditoria para os comandos.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "./dashboard";
import { createStudioApi } from "../lib/api";

const BASE = "http://127.0.0.1:8765";
const RUN_ID = "e393867a-d57b-479e-97fc-f2786668b554";
const VIDEO_ID = "f725de0d-268a-4279-b35b-1049f5eeea6a";
const CREATED_AT = "2026-09-14T13:57:53.033773Z";

const VIDEO = {
  id: VIDEO_ID,
  tema: "Ética do silêncio",
  tese: null,
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
};

const QUEUED_RUN = {
  id: RUN_ID,
  video_id: VIDEO_ID,
  status: "queued",
  priority: 50,
  queue_position: 1,
  config_snapshot: { preset: "local-recomendado-v1" },
  workflow_version: 1,
  git_commit: "contract-check",
  lease_owner: null,
  lease_expires_at: null,
  pause_requested_at: null,
  created_at: CREATED_AT,
  started_at: null,
  finished_at: null,
  failure_code: null,
  failure_message: null,
  is_read_only: false,
};

const RUNNING_RUN = {
  ...QUEUED_RUN,
  status: "running",
  lease_owner: "forge-worker-1",
  lease_expires_at: "2026-09-14T14:06:24.413047Z",
  started_at: "2026-09-14T13:58:07.090484Z",
};

const SERVICES_BODY = {
  items: [
    { name: "comfyui", state: "unavailable", message: "Comfyui não respondeu" },
    { name: "lm_studio", state: "available", message: "OK" },
    { name: "gpu", state: "available", message: "Sem residente" },
  ],
  required: ["research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"],
};

function stageView(stage: string, status: string, current = 0, total = 0) {
  return {
    stage_run: {
      id: `s-${stage}`,
      run_id: RUN_ID,
      stage,
      attempt: 1,
      status,
      current_items: current,
      total_items: total,
      progress: status === "succeeded" ? 1 : total ? current / total : 0,
      gate_status: null,
      input_hash: null,
      created_at: CREATED_AT,
      started_at: CREATED_AT,
      finished_at: status === "succeeded" ? CREATED_AT : null,
      failure_code: null,
      failure_message: null,
    },
    items: [],
    metrics: {},
  };
}

/** GET /api/runs/{id} com a run já reivindicada pelo worker (corpo real). */
const RUNNING_VIEW = {
  run: RUNNING_RUN,
  video: VIDEO,
  progress: 0.25,
  current_stage: "pesquisa",
  stages: {
    preparacao: stageView("preparacao", "succeeded"),
    pesquisa: stageView("pesquisa", "running", 4, 8),
    roteiro: stageView("roteiro", "pending"),
    plano_midia: stageView("plano_midia", "pending"),
    audio: stageView("audio", "pending"),
    imagens: stageView("imagens", "pending"),
    montagem: stageView("montagem", "pending"),
    validacao: stageView("validacao", "pending"),
  },
  artifacts: [],
};

/** Evento lido da linha `data:` do /api/events/stream. */
const LIVE_EVENT = {
  id: 12,
  run_id: RUN_ID,
  stage_run_id: "s-pesquisa",
  work_item_id: null,
  kind: "stage.progress",
  level: "info",
  message: "Pesquisa 4/8",
  payload: { current_items: 4, total_items: 8 },
  created_at: "2026-09-14T13:58:09.123456Z",
};

class FakeEventSource {
  static current: FakeEventSource | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  constructor(public readonly url: string) {
    FakeEventSource.current = this;
  }
  close() {}
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("fluxo de enfileiramento do painel", () => {
  afterEach(() => {
    FakeEventSource.current = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("enfileira pela UI, mostra o run na fila e acompanha o progresso ao vivo", async () => {
    const state = { posted: false, claimed: false };
    const calls: string[] = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown, init?: RequestInit) => {
        const path = new URL(String(url)).pathname;
        const method = init?.method ?? "GET";
        calls.push(`${method} ${path}`);

        if (path === "/api/services") return jsonResponse(SERVICES_BODY);

        if (path === "/api/videos") {
          expect(JSON.parse(String(init?.body))).toEqual({
            tema: "Ética do silêncio",
            tese: null,
            priority: 50,
            preset: "local-recomendado-v1",
          });
          state.posted = true;
          return jsonResponse({ video: VIDEO, run: QUEUED_RUN }, 201);
        }

        if (path === "/api/queue") {
          return jsonResponse(
            state.posted
              ? [
                  {
                    run: state.claimed ? RUNNING_RUN : QUEUED_RUN,
                    video: VIDEO,
                    progress: state.claimed ? 0.25 : 0,
                    current_stage: state.claimed ? "pesquisa" : "preparacao",
                  },
                ]
              : [],
          );
        }

        if (path === "/api/runs") {
          const item = {
            run: state.claimed ? RUNNING_RUN : QUEUED_RUN,
            video: VIDEO,
            progress: state.claimed ? 0.25 : 0,
            current_stage: state.claimed ? "pesquisa" : "preparacao",
          };
          const items = state.posted ? [item] : [];
          return jsonResponse({ items, total: items.length, limit: 50, offset: 0 });
        }

        if (path.startsWith("/api/runs/")) return jsonResponse(RUNNING_VIEW);

        throw new Error(`rota não esperada: ${method} ${path}`);
      }),
    );

    render(
      <Dashboard
        api={createStudioApi(BASE)}
        eventSource={FakeEventSource as unknown as typeof EventSource}
      />,
    );
    await waitFor(() => expect(screen.getByText("Nenhum vídeo aguardando")).not.toBeNull());

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Tema"), "Ética do silêncio");
    await user.click(screen.getByRole("button", { name: "Enfileirar vídeo" }));

    expect(calls).toContain("POST /api/videos");

    // O run recém-enfileirado aparece na fila.
    await waitFor(() =>
      expect(document.querySelector(".queue-list")?.textContent).toContain(
        "Ética do silêncio",
      ),
    );
    expect(screen.getByText("1 aguardando")).not.toBeNull();
    expect(screen.queryByText("Nenhum vídeo aguardando")).toBeNull();

    // O worker reivindica a run; o progresso chega pelo SSE e a run vira ativa.
    state.claimed = true;
    act(() => {
      FakeEventSource.current?.emit(LIVE_EVENT);
      FakeEventSource.current?.emit({ ...LIVE_EVENT, id: 13, message: "Pesquisa 5/8" });
    });

    await waitFor(
      () => expect(screen.getByRole("heading", { name: "Ética do silêncio" })).not.toBeNull(),
      { timeout: 3000 },
    );
    expect(screen.getByText("Run em execução")).not.toBeNull();
    expect(screen.getAllByText("25%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Pesquisa 5/8")).not.toBeNull();
    expect(FakeEventSource.current?.url).toBe(`${BASE}/api/events/stream`);

    // Os chips do pipeline seguem o status real de cada etapa.
    const chips = Array.from(
      screen.getByLabelText("Pipeline de etapas").querySelectorAll(".stage"),
    );
    const chip = (label: string) =>
      chips.find((c) => c.querySelector("b")?.textContent === label);
    expect(chip("Pesquisa")?.className).toContain("live");
    expect(chip("Roteiro")?.className).toContain("wait");
    expect(chip("Imagens")?.className).toContain("wait");
  });
});
