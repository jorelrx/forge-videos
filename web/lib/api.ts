import type {
  CreateVideoRequest,
  CreateVideoResponse,
  RunPage,
  RunSummary,
  RunView,
  CommandResponse,
  ServiceHealth,
  EventPage,
  StageName,
} from "./contracts";

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_FORGE_API_URL ?? "http://127.0.0.1:8765";

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
  pauseRun(id: string, key: string): Promise<CommandResponse>;
  resumeRun(id: string, key: string): Promise<CommandResponse>;
  retryStage(id: string, stage: StageName, key: string): Promise<CommandResponse>;
}

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
  };
}

function normalizedBase(baseUrl: string): string {
  return baseUrl.replace(/\/$/, "");
}

function endpoint(baseUrl: string, path: string): string {
  return `${normalizedBase(baseUrl)}${path}`;
}

async function request<T>(
  baseUrl: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(endpoint(baseUrl, path), {
    cache: "no-store",
    ...init,
  });
  const payload = (await response.json().catch(() => null)) as T | ApiErrorBody | null;

  if (!response.ok) {
    const error = payload as ApiErrorBody | null;
    throw new ApiError({
      status: response.status,
      code: error?.error?.code ?? "http_error",
      message: error?.error?.message ?? `Falha HTTP ${response.status}`,
    });
  }

  return payload as T;
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

export function studioEventsUrl(runId: string | null, baseUrl = DEFAULT_API_BASE): string {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return endpoint(baseUrl, `/api/events/stream${query}`);
}
