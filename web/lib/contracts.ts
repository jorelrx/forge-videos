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
  fluxo_geracao?: string;
  revisao_editorial?: boolean;
  referencias_editoriais?: string;
}

export interface DecisaoConflitoPauta {
  artefato_id: string;
  acao: "aceitar" | "editar" | "cancelar";
  promessa?: string;
  recorte?: string;
}

export interface EscolhaEditorial {
  artefato_id: string;
  indice: number;
}

export interface DecisaoAbertura {
  artefato_id: string;
  acao: "aprovar" | "audio" | "imagem";
  item?: string;
  orientacao?: string;
}

export interface NovoFluxoGeracao {
  nome: string;
  descricao: string;
  instrucoes: string;
}

export interface FluxoGeracao extends Omit<NovoFluxoGeracao, "instrucoes"> {
  id: string;
  instrucoes: string | null;
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
  /** A configuração atual usa o serviço (ausente = API antiga, conta como habilitado). */
  enabled?: boolean;
  /** Etapas em que o serviço entra: pesquisa, roteiro, revisão, imagens... */
  usos?: string[];
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

export type PublicacaoEtapa = "enviando" | "thumbnail" | "legenda" | "concluida" | "falhou";
export type PublicacaoParte = "pendente" | "ok" | "recusada";

export interface PublicacaoEstado {
  etapa: PublicacaoEtapa;
  titulo: string;
  publicar_em: string | null;
  upload_uri: string | null;
  bytes_enviados: number;
  total_bytes: number;
  video_id: string | null;
  thumbnail: PublicacaoParte;
  legenda: PublicacaoParte;
  avisos: string[];
  erro: string | null;
  erro_codigo: string | null;
  atualizado_em: string;
  url: string | null;
  canal_id?: string | null;
  canal_titulo?: string | null;
}

export interface PublicacaoView {
  estado: PublicacaoEstado | null;
  em_andamento: boolean;
  conectado: boolean;
}

export interface Medicao {
  janela: 7 | 28;
  visualizacoes: number;
  impressoes: number | null;
  ctr: number | null;
  origem_trafego: string;
  retencao_30s: number | null;
  percentual_assistido: number | null;
  comentarios: number | null;
  respostas_lidas: number | null;
  respostas_substantivas: number | null;
  cliques_tela_final: number | null;
}

export interface Desempenho {
  video_id: string;
  titulo: string;
  fluxo_geracao: string | null;
  medicoes: (Medicao & { comentarios_por_mil: number | null })[];
}

export interface PublicacaoRequest {
  titulo: string;
  publicar_em: string | null;
  canal_id: string | null;
}

export interface YouTubeCanal {
  id: string;
  titulo: string;
  thumbnail: string | null;
  padrao: boolean;
}

export type YouTubeLoginStatus = "inativo" | "aguardando" | "concluido" | "falhou";

export interface YouTubeLogin {
  status: YouTubeLoginStatus;
  url: string | null;
  erro: string | null;
  canal_id: string | null;
}

export interface YouTubeView {
  cliente_configurado: boolean;
  canais: YouTubeCanal[];
  login: YouTubeLogin;
}
