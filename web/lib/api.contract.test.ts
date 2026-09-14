/**
 * Contract test: every endpoint the panel calls, checked against what the
 * FastAPI app actually exposes and actually returns.
 *
 * The fixtures below are verbatim copies of responses captured over real HTTP
 * (uvicorn on 127.0.0.1:8799, temp SQLite DB, stubbed health probes) via
 * `GET /openapi.json` plus endpoint calls. See the audit report for the
 * commands; no fixture here was hand-written.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { artifactContentUrl, createStudioApi, studioEventsUrl } from "./api";

/** Sorted `METHOD path` list served by GET /openapi.json on the real API. */
const REAL_ROUTES: readonly string[] = [
  "GET /api/artifacts/{artifact_id}/content",
  "GET /api/config/effective",
  "GET /api/events/stream",
  "GET /api/queue",
  "GET /api/runs",
  "GET /api/runs/{run_id}",
  "GET /api/runs/{run_id}/artifacts",
  "GET /api/runs/{run_id}/events",
  "GET /api/services",
  "POST /api/runs/{run_id}/pause",
  "POST /api/runs/{run_id}/resume",
  "POST /api/runs/{run_id}/stages/{stage}/retry",
  "POST /api/videos",
];

const BASE = "http://127.0.0.1:8765";

const VIDEO = {
  id: "f725de0d-268a-4279-b35b-1049f5eeea6a",
  tema: "Contrato de ações",
  tese: null,
  created_at: "2026-09-14T13:57:53.033773Z",
  updated_at: "2026-09-14T13:57:53.033773Z",
};

const RUN = {
  id: "e393867a-d57b-479e-97fc-f2786668b554",
  video_id: VIDEO.id,
  status: "queued",
  priority: 50,
  queue_position: 1,
  config_snapshot: { preset: "local-recomendado-v1" },
  workflow_version: 1,
  git_commit: "contract-check",
  lease_owner: null,
  lease_expires_at: null,
  pause_requested_at: null,
  created_at: "2026-09-14T13:57:53.033773Z",
  started_at: null,
  finished_at: null,
  failure_code: null,
  failure_message: null,
  is_read_only: false,
};

/** POST /api/videos -> 201 (real body). */
const CREATE_BODY = { video: VIDEO, run: RUN };

/** GET /api/queue -> 200 (real body). */
const QUEUE_BODY = [{ run: RUN, video: VIDEO, progress: 0, current_stage: "preparacao" }];

/** GET /api/runs/{run_id} -> 200 (real body, one stage running). */
const RUN_VIEW_BODY = {
  run: { ...RUN, status: "running", lease_owner: "forge-worker-1" },
  video: VIDEO,
  progress: 0.125,
  current_stage: "pesquisa",
  stages: {
    preparacao: {
      stage_run: {
        id: "s0",
        run_id: RUN.id,
        stage: "preparacao",
        attempt: 1,
        status: "succeeded",
        current_items: 0,
        total_items: 0,
        progress: 1.0,
        gate_status: "ok",
        input_hash: null,
        created_at: RUN.created_at,
        started_at: RUN.created_at,
        finished_at: RUN.created_at,
        failure_code: null,
        failure_message: null,
      },
      items: [],
      metrics: {},
    },
    pesquisa: {
      stage_run: {
        id: "s1",
        run_id: RUN.id,
        stage: "pesquisa",
        attempt: 1,
        status: "running",
        current_items: 4,
        total_items: 8,
        progress: 0.5,
        gate_status: null,
        input_hash: null,
        created_at: RUN.created_at,
        started_at: RUN.created_at,
        finished_at: null,
        failure_code: null,
        failure_message: null,
      },
      items: [],
      metrics: {},
    },
  },
  artifacts: [],
};

/** GET /api/runs/{run_id}/events -> 200 (real body). */
const EVENTS_BODY = {
  items: [
    {
      id: 1,
      run_id: RUN.id,
      stage_run_id: null,
      work_item_id: null,
      kind: "run.queued",
      level: "info",
      message: "Run enfileirada",
      payload: {},
      created_at: "2026-09-14T13:57:53.033773Z",
    },
  ],
  next_before_id: null,
};

/** GET /api/services -> 200 (real envelope; `gpu` keeps the extra fields). */
const SERVICES_BODY = {
  items: [
    { name: "comfyui", state: "unavailable", message: "Comfyui não respondeu" },
    { name: "lm_studio", state: "available", message: "OK" },
    { name: "gpu", state: "available", message: "Sem residente" },
    { name: "tts", state: "unavailable", message: "Tts não respondeu" },
  ],
  required: ["research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"],
};

/** POST /api/runs/{run_id}/pause with Idempotency-Key -> 200 (real body). */
const COMMAND_BODY = {
  id: "565753f7-d780-49d0-91f7-8f21e81cf4db",
  run_id: RUN.id,
  type: "pause",
  stage: null,
  idempotency_key: "a3",
  status: "accepted",
  result: {},
  created_at: "2026-09-14T13:57:53.097507Z",
  applied_at: null,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function template(method: string, url: string): string {
  const path = new URL(url).pathname;
  return `${method} ${path
    .replace(/\/api\/runs\/[^/]+\/stages\/[^/]+\/retry/, "/api/runs/{run_id}/stages/{stage}/retry")
    .replace(/\/api\/runs\/[^/]+\/events/, "/api/runs/{run_id}/events")
    .replace(/\/api\/runs\/[^/]+/, "/api/runs/{run_id}")
    .replace(/\/api\/artifacts\/[^/]+\/content/, "/api/artifacts/{artifact_id}/content")}`;
}

describe("studio HTTP contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("chama somente rotas que a API expõe (GET /openapi.json)", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
      calls.push(template(init?.method ?? "GET", String(url)));
      const payload = String(url).includes("/events")
        ? EVENTS_BODY
        : String(url).includes("/services")
          ? SERVICES_BODY
          : String(url).includes("/queue")
            ? QUEUE_BODY
            : String(url).includes("/api/videos")
              ? CREATE_BODY
              : String(url).includes("/pause") ||
                  String(url).includes("/resume") ||
                  String(url).includes("/retry")
                ? COMMAND_BODY
                : RUN_VIEW_BODY;
      const status = String(url).includes("/api/videos") ? 201 : 200;
      return jsonResponse(payload, status);
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createStudioApi(BASE);

    await api.getQueue();
    await api.getRuns();
    await api.getRun(RUN.id);
    await api.getServices();
    await api.getEvents(RUN.id);
    await api.createVideo({ tema: "T", tese: null, priority: 50, preset: "local-recomendado-v1" });
    await api.pauseRun(RUN.id, "k1");
    await api.resumeRun(RUN.id, "k2");
    await api.retryStage(RUN.id, "roteiro", "k3");

    for (const call of calls) {
      expect(REAL_ROUTES).toContain(call);
    }
    expect(calls).toContain("POST /api/videos");
    expect(calls).toContain("POST /api/runs/{run_id}/stages/{stage}/retry");
  });

  it("envia Idempotency-Key nos comandos e Content-Type no create", async () => {
    const fetchMock = vi.fn(async (url: unknown) =>
      jsonResponse(String(url).includes("/api/videos") ? CREATE_BODY : COMMAND_BODY,
        String(url).includes("/api/videos") ? 201 : 200),
    );
    vi.stubGlobal("fetch", fetchMock);
    const api = createStudioApi(BASE);

    await api.pauseRun(RUN.id, "key-pause");
    await api.createVideo({ tema: "T", tese: null, priority: 50, preset: "local-recomendado-v1" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${BASE}/api/runs/${RUN.id}/pause`,
      expect.objectContaining({
        method: "POST",
        headers: { "Idempotency-Key": "key-pause" },
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${BASE}/api/videos`,
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tema: "T",
          tese: null,
          priority: 50,
          preset: "local-recomendado-v1",
        }),
      }),
    );
  });

  it("consome a projeção real: 201 create, fila, página de runs, run view e eventos", async () => {
    const payloads: Record<string, unknown> = {
      "/api/videos": CREATE_BODY,
      "/api/queue": QUEUE_BODY,
      "/api/runs": { items: QUEUE_BODY, total: 1, limit: 50, offset: 0 },
      [`/api/runs/${RUN.id}`]: RUN_VIEW_BODY,
      [`/api/runs/${RUN.id}/events`]: EVENTS_BODY,
      "/api/services": SERVICES_BODY,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const path = new URL(String(url)).pathname;
        const payload = payloads[path];
        expect(payload, `no fixture for ${path}`).toBeDefined();
        return jsonResponse(payload, path === "/api/videos" ? 201 : 200);
      }),
    );
    const api = createStudioApi(BASE);

    const created = await api.createVideo({
      tema: "Contrato de ações",
      tese: null,
      priority: 50,
      preset: "local-recomendado-v1",
    });
    expect(created.run.id).toBe(RUN.id);
    expect(created.run.status).toBe("queued");
    expect(created.video.tema).toBe("Contrato de ações");

    const queue = await api.getQueue();
    expect(queue).toHaveLength(1);
    expect(queue[0].run.id).toBe(RUN.id);
    expect(queue[0].video.tema).toBe("Contrato de ações");
    expect(typeof queue[0].progress).toBe("number");

    const page = await api.getRuns(50, 0);
    expect(page).toMatchObject({ total: 1, limit: 50, offset: 0 });
    expect(page.items[0].run.id).toBe(RUN.id);

    const view = await api.getRun(RUN.id);
    expect(view.current_stage).toBe("pesquisa");
    expect(view.stages.pesquisa.stage_run.status).toBe("running");
    expect(view.stages.pesquisa.stage_run.total_items).toBe(8);

    const events = await api.getEvents(RUN.id);
    expect(events.items[0].kind).toBe("run.queued");
    expect(typeof events.items[0].id).toBe("number");

    const services = await api.getServices();
    expect(services.comfyui.state).toBe("unavailable");
    expect(services.gpu.name).toBe("gpu");
  });

  it("monta as URLs de SSE e de conteúdo de artefato que a API expõe", () => {
    expect(studioEventsUrl(null, BASE)).toBe(`${BASE}/api/events/stream`);
    expect(studioEventsUrl(RUN.id, BASE)).toBe(
      `${BASE}/api/events/stream?run_id=${RUN.id}`,
    );
    expect(artifactContentUrl("artifact-1", BASE)).toBe(
      `${BASE}/api/artifacts/artifact-1/content`,
    );
  });

  it("expõe a mensagem real do FastAPI (envelope `detail`) nos erros", async () => {
    // Capturado: retry enquanto a run está em execução.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            detail: {
              error: { code: "transition_invalid", message: "run: running -> queued" },
            },
          },
          409,
        ),
      ),
    );
    const api = createStudioApi(BASE);

    await expect(api.retryStage(RUN.id, "roteiro", "k1")).rejects.toMatchObject({
      failure: {
        status: 409,
        code: "transition_invalid",
        message: "run: running -> queued",
      },
    });

    // Capturado: comando sem Idempotency-Key.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            detail: {
              error: {
                code: "validation_error",
                message: "Idempotency-Key header is required",
              },
            },
          },
          422,
        ),
      ),
    );
    await expect(api.pauseRun(RUN.id, "")).rejects.toMatchObject({
      failure: {
        status: 422,
        code: "validation_error",
        message: "Idempotency-Key header is required",
      },
    });

    // Capturado: corpo 422 do pydantic (lista em `detail`).
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            detail: [
              {
                type: "string_too_short",
                loc: ["body", "tema"],
                msg: "String should have at least 1 character",
                input: "",
                ctx: { min_length: 1 },
              },
            ],
          },
          422,
        ),
      ),
    );
    await expect(
      api.createVideo({ tema: "", tese: null, priority: 50, preset: "local-recomendado-v1" }),
    ).rejects.toMatchObject({
      failure: {
        status: 422,
        message: "String should have at least 1 character",
      },
    });
  });

  it("mantém a mensagem genérica quando o corpo de erro não é o envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>502</html>", { status: 502 })),
    );
    const api = createStudioApi(BASE);

    await expect(api.getQueue()).rejects.toMatchObject({
      failure: { status: 502, code: "http_error", message: "Falha HTTP 502" },
    });
  });
});
