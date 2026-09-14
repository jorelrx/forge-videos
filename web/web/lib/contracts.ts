export interface Video { id: string; tema: string; tese?: string | null; }
export interface Run { id: string; video_id: string; status: string; priority: number; }
export interface StageRun { id: string; run_id: string; stage: string; attempt: number; status: string; progress: number; }
export interface Artifact { id: string; run_id: string; stage_run_id: string; kind: string; relative_path: string; mime_type: string; is_current: boolean; }
export interface WorkItem { id: string; stage_run_id: string; item_key: string; status: string; }
export interface Event { id: number; run_id?: string; kind: string; level: string; message: string; payload: Record<string, unknown>; }
export interface Command { id: string; run_id: string; type: string; stage?: string; status: string; }
export type RunStatus = string;
export type StageName = string;
export interface CreateVideoInput { tema: string; tese?: string | null; priority: number; preset: string; }
export interface CreateVideoResponse { video: Video; run: Run; }
export interface RunSummary { run: Run; video: Video; progress: number; current_stage: StageName | null; }
export interface StageView { stage_run: StageRun; items: WorkItem[]; metrics: Record<string, unknown>; }
export interface RunView extends RunSummary { stages: Record<StageName, StageView>; artifacts: Artifact[]; }
export interface RunPage { items: RunSummary[]; total: number; limit: number; offset: number; }
export interface EventPage { items: Event[]; next_before_id?: number | null; }
export interface StudioEvent { id: number; kind: string; message: string; payload?: Record<string, unknown>; }
export interface ServiceHealth { name: string; state: string; message: string; latency_ms?: number | null; details?: Record<string, unknown>; }
export interface EffectiveConfig { preset: Record<string, unknown>; api: { host: string; port: number }; web?: { host: string; port: number }; worker?: { lease_seconds: number; heartbeat_seconds: number }; services?: Record<string, unknown>; }
export interface ApiErrorBody { error: { code: string; message: string; }; }
