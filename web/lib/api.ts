import type {
  Artifact,
  CreateVideoRequest,
  CreateVideoResponse,
  RunPage,
  RunSummary,
  RunView,
  CommandResponse,
  ServiceHealth,
  EventPage,
  FluxoGeracao,
  NovoFluxoGeracao,
  EscolhaEditorial,
  DecisaoAbertura,
  Desempenho,
  Medicao,
  StageName,
  PublicacaoRequest,
  PublicacaoView,
} from "./contracts";

const DEFAULT_API_BASE = "";
export const SESSAO_EXPIRADA = "forge:sessao-expirada";
let requisicoes = new AbortController();

export function cancelarRequisicoes() {
  requisicoes.abort();
  requisicoes = new AbortController();
}

export function canalDaAba(): string | null {
  if (typeof window === "undefined") return null;
  const segmento = /^\/canais\/([^/]+)/.exec(window.location.pathname)?.[1];
  return segmento ? decodeURIComponent(segmento) : null;
}

export interface ApiFailure {
  readonly status: number;
  readonly code: string;
  readonly message: string;
}

export class ApiError extends Error {
  constructor(
    public readonly failure: ApiFailure,
    message?: string,
  ) {
    super(message ?? failure.message);
    this.name = "ApiError";
  }
}

export interface StudioApi {
  getQueue(): Promise<RunSummary[]>;
  getRuns(limit?: number, offset?: number): Promise<RunPage>;
  getRun(id: string): Promise<RunView>;
  getServices(): Promise<Record<string, ServiceHealth>>;
  getEvents(runId: string, beforeId?: number): Promise<EventPage>;
  createVideo(input: CreateVideoRequest): Promise<CreateVideoResponse>;
  getGenerationFlows(): Promise<FluxoGeracao[]>;
  createGenerationFlow(input: NovoFluxoGeracao): Promise<FluxoGeracao>;
  pauseRun(id: string, key: string): Promise<CommandResponse>;
  resumeRun(id: string, key: string): Promise<CommandResponse>;
  retryStage(id: string, stage: StageName, key: string): Promise<CommandResponse>;
  escolherProposta?(id: string, input: EscolhaEditorial): Promise<unknown>;
  decidirAbertura?(id: string, input: DecisaoAbertura): Promise<unknown>;
  decidirConflitoPauta?(id: string, input: import("./contracts").DecisaoConflitoPauta): Promise<unknown>;
}

interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

interface ApiErrorBody extends ApiErrorEnvelope {
  /**
   * O FastAPI embrulha o detail do HTTPException em `detail`, e o
   * RequestValidationError usa uma lista em `detail`. handlers de app
   * (app.py) devolvem o envelope `error` no topo.
   */
  detail?: ApiErrorEnvelope | string | { msg?: string }[];
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function decodeFailure(status: number, payload: unknown): ApiFailure {
  const fallback: ApiFailure = {
    status,
    code: "http_error",
    message: `Falha HTTP ${status}`,
  };
  if (!isEnvelope(payload)) return fallback;

  const body = payload as ApiErrorBody;
  const detail = body.detail;
  const envelope = body.error ?? (isEnvelope(detail) ? detail.error : undefined);
  if (envelope?.message) {
    return {
      status,
      code: envelope.code ?? "http_error",
      message: envelope.message,
    };
  }

  if (Array.isArray(detail)) {
    const first = detail.find((item) => typeof item?.msg === "string");
    if (first?.msg) {
      return { status, code: "validation_error", message: first.msg };
    }
  }

  if (typeof detail === "string" && detail) {
    return { status, code: "http_error", message: detail };
  }

  return fallback;
}

function normalizedBase(baseUrl: string): string {
  return baseUrl.replace(/\/$/, "");
}

function endpoint(baseUrl: string, path: string): string {
  const canal = canalDaAba();
  const query = canal ? (path.includes("?") ? "&" : "?") + "canal_id=" + encodeURIComponent(canal) : "";
  return normalizedBase(baseUrl) + path + query;
}

async function request<T>(
  baseUrl: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return studioRequest<T>(endpoint(baseUrl, path), init);
}

export async function studioRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await studioFetch(url, init);
  const payload = (await response.json().catch(() => null)) as T | ApiErrorBody | null;
  if (!response.ok) throw new ApiError(decodeFailure(response.status, payload));
  return payload as T;
}

export async function studioFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const signal = init.signal ? AbortSignal.any([init.signal, requisicoes.signal]) : requisicoes.signal;
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    signal,
  });
  signal.throwIfAborted();
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSAO_EXPIRADA));
  }
  return response;
}

function commandRequest(
  baseUrl: string,
  path: string,
  idempotencyKey: string,
): Promise<CommandResponse> {
  return request(baseUrl, path, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function createStudioApi(baseUrl = DEFAULT_API_BASE): StudioApi {
  return {
    getQueue: () => request<RunSummary[]>(baseUrl, "/api/queue"),
    getRuns: (limit = 50, offset = 0) =>
      request<RunPage>(baseUrl, `/api/runs?limit=${limit}&offset=${offset}`),
    getRun: (id) => request<RunView>(baseUrl, `/api/runs/${encodeURIComponent(id)}`),
    async getServices() {
      const response = await request<{ items: ServiceHealth[] }>(baseUrl, "/api/services");
      return Object.fromEntries(response.items.map((service) => [service.name, service]));
    },
    getEvents: (runId, beforeId) => {
      const suffix = beforeId === undefined ? "" : `?before_id=${beforeId}`;
      return request<EventPage>(
        baseUrl,
        `/api/runs/${encodeURIComponent(runId)}/events${suffix}`,
      );
    },
    createVideo: (input) =>
      request<CreateVideoResponse>(baseUrl, "/api/videos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    getGenerationFlows: () => request<FluxoGeracao[]>(baseUrl, "/api/fluxos-geracao"),
    createGenerationFlow: (input) =>
      request<FluxoGeracao>(baseUrl, "/api/fluxos-geracao", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    escolherProposta: (id, input) => request(baseUrl, "/api/runs/" + encodeURIComponent(id) + "/proposta-editorial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    decidirAbertura: (id, input) => request(baseUrl, "/api/runs/" + encodeURIComponent(id) + "/previa-abertura", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    decidirConflitoPauta: (id, input) => request(baseUrl, "/api/runs/" + encodeURIComponent(id) + "/conflito-pauta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    pauseRun: (id, key) =>
      commandRequest(baseUrl, `/api/runs/${encodeURIComponent(id)}/pause`, key),
    resumeRun: (id, key) =>
      commandRequest(baseUrl, `/api/runs/${encodeURIComponent(id)}/resume`, key),
    retryStage: (id, stage, key) =>
      commandRequest(
        baseUrl,
        `/api/runs/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}/retry`,
        key,
      ),
  };
}

export function artifactContentUrl(id: string, baseUrl = DEFAULT_API_BASE): string {
  return endpoint(baseUrl, `/api/artifacts/${encodeURIComponent(id)}/content`);
}

/**
 * URL que faz o navegador salvar o arquivo. O painel e a API ficam em portas
 * diferentes, e entre origens o atributo `download` do link é ignorado: quem
 * manda salvar é o `Content-Disposition` que a API devolve com `download=1`.
 */
export function artifactDownloadUrl(id: string, baseUrl = DEFAULT_API_BASE): string {
  return endpoint(baseUrl, `/api/artifacts/${encodeURIComponent(id)}/content?download=1`);
}

/** Artefatos correntes de uma run (`GET /api/runs/{run_id}/artifacts`). */
export function listRunArtifacts(runId: string, baseUrl = DEFAULT_API_BASE): Promise<Artifact[]> {
  return request<Artifact[]>(baseUrl, `/api/runs/${encodeURIComponent(runId)}/artifacts`);
}

/** Estado da publicação no YouTube (`GET /api/runs/{run_id}/publication`). */
export function getPublication(runId: string, baseUrl = DEFAULT_API_BASE): Promise<PublicacaoView> {
  return request<PublicacaoView>(baseUrl, `/api/runs/${encodeURIComponent(runId)}/publication`);
}

export function getPerformance(runId: string, baseUrl = DEFAULT_API_BASE): Promise<Desempenho> {
  return request(baseUrl, "/api/runs/" + encodeURIComponent(runId) + "/desempenho");
}

export function savePerformance(runId: string, medicao: Medicao, baseUrl = DEFAULT_API_BASE): Promise<Desempenho> {
  return request(baseUrl, "/api/runs/" + encodeURIComponent(runId) + "/desempenho", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(medicao),
  });
}

/** Inicia ou retoma o envio ao YouTube (`POST /api/runs/{run_id}/publication`, 202). */
export function publishRun(
  runId: string,
  body: PublicacaoRequest,
  baseUrl = DEFAULT_API_BASE,
): Promise<PublicacaoView> {
  return request<PublicacaoView>(baseUrl, `/api/runs/${encodeURIComponent(runId)}/publication`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function studioEventsUrl(runId: string | null, baseUrl = DEFAULT_API_BASE): string {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return endpoint(baseUrl, `/api/events/stream${query}`);
}
