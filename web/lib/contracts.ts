export type RunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "pausing"
  | "paused"
  | "validating"
  | "completed"
  | "failed"
  | "interrupted"
  | "cancelled";

export type StageName =
  | "preparacao"
  | "pesquisa"
  | "roteiro"
  | "plano_midia"
  | "audio"
  | "imagens"
  | "montagem"
  | "validacao";

export type StageStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "pausing"
  | "paused"
  | "interrupted"
  | "invalidated";

export type ItemStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "invalidated";

export type CommandType = "pause" | "resume" | "retry_stage";

export type CommandStatus =
  | "pending"
  | "accepted"
  | "applied"
  | "rejected";

export type FailureClass =
  | "transient"
  | "capacity"
  | "deterministic"
  | "process"
  | "user"
  | "item";

export type ChildEventKind =
  | "item.planned"
  | "item.started"
  | "item.succeeded"
  | "item.failed"
  | "artifact.created"
  | "stage.progress"
  | "stage.result";

/**
 * A API serializa `UtcDatetime` (pydantic AwareDatetime) como string ISO-8601
 * com sufixo Z — ex.: "2026-09-14T13:57:53.033773Z". `StudioEvent` já usava
 * `string`; o resto do painel declarava um objeto de campos, que nunca chega
 * nesse formato pela rede.
 */
export type UtcDatetime = string;

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

export type JsonObject = Record<string, JsonValue>;

export interface Video {
  id: string;
  tema: string;
  tese: string | null;
  created_at: UtcDatetime;
  updated_at: UtcDatetime;
}

export interface Run {
  id: string;
  video_id: string;
  status: RunStatus;
  priority: number;
  queue_position: number;
  config_snapshot: JsonObject;
  workflow_version: number;
  git_commit: string;
  lease_owner: string | null;
  lease_expires_at: UtcDatetime | null;
  pause_requested_at: UtcDatetime | null;
  created_at: UtcDatetime;
  started_at: UtcDatetime | null;
  finished_at: UtcDatetime | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface StageRun {
  id: string;
  run_id: string;
  stage: StageName;
  attempt: number;
  status: StageStatus;
  current_items: number;
  total_items: number;
  progress: number;
  gate_status: string | null;
  input_hash: string | null;
  created_at: UtcDatetime;
  started_at: UtcDatetime | null;
  finished_at: UtcDatetime | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface StageResult {
  gate_status: string | null;
  current_items: number;
  total_items: number;
  failure_code: string | null;
  failure_message: string | null;
  outputs: JsonObject;
}

export interface WorkItem {
  id: string;
  stage_run_id: string;
  item_key: string;
  status: ItemStatus;
  input: JsonObject;
  input_hash: string;
  attempts: number;
  duration_ms: number | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface Artifact {
  id: string;
  run_id: string;
  stage_run_id: string;
  work_item_id: string | null;
  kind: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  metadata: JsonObject;
  is_current: boolean;
  created_at: UtcDatetime;
}

export interface Event {
  id: number;
  run_id: string | null;
  stage_run_id: string | null;
  work_item_id: string | null;
  kind: string;
  level: string;
  message: string;
  payload: JsonObject;
  created_at: UtcDatetime;
}

export interface Command {
  id: string;
  run_id: string;
  type: CommandType;
  stage: StageName | null;
  idempotency_key: string;
  status: CommandStatus;
  result: JsonObject;
  created_at: UtcDatetime;
  applied_at: UtcDatetime | null;
}

// ---- API contracts (forge.api.contracts) ----

export interface CreateVideoRequest {
  tema: string;
  tese: string | null;
  priority: number;
  preset: "local-recomendado-v1";
}

export interface CreateVideoResponse {
  video: JsonObject;
  run: JsonObject;
}

export interface VideoSummary {
  id: string;
  tema: string;
  tese: string | null;
  created_at: UtcDatetime;
  updated_at: UtcDatetime;
}

export interface RunSummary {
  run: Run;
  video: VideoSummary;
  progress: number;
  current_stage: StageName | null;
}

export interface RunPage {
  items: RunSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface CommandResponse {
  id: string;
  run_id: string;
  type: CommandType;
  stage: StageName | null;
  idempotency_key: string;
  status: CommandStatus;
  result: JsonObject;
  created_at: UtcDatetime;
  applied_at: UtcDatetime | null;
}

export interface EventPage {
  items: Event[];
  next_before_id: number | null;
}

export interface ServiceHealth {
  name: string;
  state: string;
  message: string;
  latency_ms?: number | null;
  details?: JsonObject;
}

export interface EffectiveConfig {
  preset: JsonObject;
  api: JsonObject;
}

export interface ArtifactListItem {
  id: string;
  run_id: string;
  stage_run_id: string;
  work_item_id: string | null;
  kind: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  metadata: JsonObject;
  is_current: boolean;
  created_at: UtcDatetime;
}

export interface ArtifactPreview {
  id: string;
  run_id: string;
  kind: string;
  relative_path: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
}

// ---- Dashboard-friendly derived types ----

export interface StageView {
  stage_run: StageRun;
  items: WorkItem[];
  metrics: JsonObject;
}

export interface RunView extends RunSummary {
  stages: Record<StageName, StageView>;
  artifacts: Artifact[];
}

export interface StudioEvent {
  id: number;
  run_id: string | null;
  stage_run_id?: string | null;
  work_item_id?: string | null;
  kind: string;
  level: string;
  message: string;
  payload: JsonObject;
  created_at: string;
}
