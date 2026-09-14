export type RunStatus =
  | "queued" | "preparing" | "running" | "pausing" | "paused"
  | "validating" | "completed" | "failed" | "interrupted" | "cancelled";

export type StageName =
  | "preparacao" | "pesquisa" | "roteiro" | "plano_midia"
  | "audio" | "imagens" | "montagem" | "validacao";

export interface StudioEvent {
  id: number;
  run_id?: string;
  stage?: string;
  item_id?: string;
  kind: string;
  level?: string;
  message?: string;
  progress?: { current: number; total: number };
  metrics?: Record<string, unknown>;
  created_at?: string;
}

export interface RunSummary {
  run: { id: string; status: RunStatus; [key: string]: unknown };
  video: { id: string; tema: string; [key: string]: unknown };
  progress: number;
  current_stage: StageName | null;
}

export interface ServiceHealth {
  name: string;
  state: string;
  message: string;
  latency_ms?: number | null;
  details?: Record<string, unknown>;
}
