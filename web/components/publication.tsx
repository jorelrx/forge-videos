"use client";

import { DesempenhoPublicacao } from "./desempenho";

import React from "react";
import {
  artifactContentUrl, artifactDownloadUrl, disconnectChannel, getPublication, getYouTube, listRunArtifacts,
  publishRun, setDefaultChannel, startYouTubeLogin, uploadYouTubeClient,
} from "../lib/api";
import type { Artifact, PublicacaoView, RunSummary, YouTubeView } from "../lib/contracts";
import { serviceStatusLabel } from "../lib/stage-map";
import { PageHeader } from "./screens";

/**
 * Aba Publicação: o que o dono do canal cola e sobe à mão no YouTube, terminada
 * a run. Lê só artefatos existentes (`embalagem`, `thumbnail.jpg`,
 * `legendas.srt`, `video/final.mp4`); qualquer um pode faltar e vira estado
 * vazio daquela parte, nunca erro.
 */

/** Limites do gate do backend (services/qualidade_embalagem.py). */
const TITULO_RECOMENDADO = 60;
const TITULO_MAXIMO = 70;
const DESCRICAO_MAXIMO = 5000;
const TAGS_MAXIMO = 500;

const CHECKLIST = [
  { id: "thumbnail", label: "Thumbnail enviada" },
  { id: "legenda", label: "Legenda em português enviada" },
  { id: "capitulos", label: "Capítulos na descrição" },
  { id: "comentario", label: "Comentário fixado" },
  { id: "sintetico", label: "Declaração de conteúdo alterado ou sintético do YouTube revisada" },
] as const;

type Embalagem = {
  titulos?: { texto: string; angulo?: string }[];
  thumbnail?: { texto?: string; prompt?: string };
  descricao?: string;
  capitulos_estimados?: boolean;
  tags?: string[];
  comentario_fixado?: string;
};

type Level = "ok" | "warn" | "error";

export interface PublicationProps {
  runs: RunSummary[];
  loadArtifacts?: (runId: string) => Promise<Artifact[]>;
}

/** Conta como o `len()` do Python: por code point, não por unidade UTF-16. */
function chars(text: string): number {
  return Array.from(text).length;
}

function latest(artifacts: Artifact[], match: (artifact: Artifact) => boolean): Artifact | undefined {
  return artifacts
    .filter((artifact) => artifact.is_current !== false && match(artifact))
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
}

function completedAt(summary: RunSummary): string {
  return summary.run.finished_at ?? summary.run.created_at ?? "";
}

function defaultRunId(runs: RunSummary[]): string | null {
  const completed = runs
    .filter((summary) => summary.run?.status === "completed")
    .sort((a, b) => completedAt(b).localeCompare(completedAt(a)));
  return completed[0]?.run.id ?? null;
}

function fileName(artifact: Artifact): string {
  return artifact.relative_path.split("/").pop() ?? artifact.relative_path;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="output-empty pub-empty"><span aria-hidden="true">◇</span><h3>{title}</h3><p>{detail}</p></div>;
}

function CopyButton({ label, text }: { label: string; text: string }) {
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  React.useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) {
      setState("failed");
      return;
    }
    try {
      await clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <span className="pub-copy">
      <button className="btn" type="button" aria-label={label} onClick={copy}>Copiar</button>
      <span className={`pub-copy-status ${state}`} role="status" aria-live="polite">
        {state === "copied" ? "Copiado" : state === "failed" ? "Copie manualmente" : ""}
      </span>
    </span>
  );
}

function Counter({ testId, count, max, recommended, warnText }: {
  testId: string; count: number; max: number; recommended?: number; warnText?: string;
}) {
  const level: Level = count > max ? "error" : recommended !== undefined && count > recommended ? "warn" : "ok";
  const note = level === "error" ? "acima do limite" : level === "warn" ? warnText ?? "perto do limite" : "";
  return (
    <span className={`pub-counter ${level}`} data-testid={testId} data-level={level}>
      {count}/{max}{note && ` · ${note}`}
    </span>
  );
}

function Field({ title, headingId, actions, children }: {
  title: string; headingId: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="pub-field" aria-labelledby={headingId}>
      <div className="pub-field-head">
        <h3 id={headingId}>{title}</h3>
        {actions && <div className="pub-field-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

type EmbalagemState = { data: Embalagem | null; loading: boolean; failed: boolean };

function useEmbalagem(artifact: Artifact | undefined) {
  const [state, setState] = React.useState<{ data: Embalagem | null; loading: boolean; failed: boolean }>({
    data: null, loading: Boolean(artifact), failed: false,
  });
  const id = artifact?.id;
  React.useEffect(() => {
    if (!id) {
      setState({ data: null, loading: false, failed: false });
      return;
    }
    const controller = new AbortController();
    setState({ data: null, loading: true, failed: false });
    fetch(artifactContentUrl(id), { cache: "no-store", signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("embalagem_indisponivel");
        return response.text();
      })
      .then((raw) => {
        if (controller.signal.aborted) return;
        const parsed = JSON.parse(raw) as unknown;
        if (typeof parsed !== "object" || parsed === null) throw new Error("embalagem_invalida");
        setState({ data: parsed as Embalagem, loading: false, failed: false });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState({ data: null, loading: false, failed: true });
      });
    return () => controller.abort();
  }, [id]);
  return state;
}

function parseView(value: unknown): PublicacaoView | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Partial<PublicacaoView>;
  if (typeof v.conectado !== "boolean") return null;
  return { estado: v.estado ?? null, em_andamento: v.em_andamento === true, conectado: v.conectado };
}

const POLL_MS = 3000;
const LOGIN_POLL_MS = 2000;

/** Resposta fora do contrato vira `null` (painel some), nunca exceção de render. */
function parseYt(value: unknown): YouTubeView | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Partial<YouTubeView>;
  if (typeof v.cliente_configurado !== "boolean" || !Array.isArray(v.canais)) return null;
  const login = v.login ?? { status: "inativo", url: null, erro: null, canal_id: null };
  return { cliente_configurado: v.cliente_configurado, canais: v.canais, login };
}

function mensagem(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Conta do YouTube: cliente OAuth, login no Google (janela aberta no clique,
 * para o bloqueador de pop-up não barrar) e lista de canais conectados.
 */
function YouTubeAccount({
  view, onView, error, setError, loginUrl, setLoginUrl,
}: {
  view: YouTubeView | null;
  onView: (view: YouTubeView) => void;
  error: string | null;
  setError: (message: string | null) => void;
  loginUrl: string | null;
  setLoginUrl: (url: string | null) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const aguardando = view?.login.status === "aguardando";

  React.useEffect(() => {
    if (!aguardando) return;
    let active = true;
    const timer = setInterval(() => {
      getYouTube()
        .then((next) => { if (active) { const parsed = parseYt(next); if (parsed) onView(parsed); } })
        .catch(() => undefined);
    }, LOGIN_POLL_MS);
    return () => { active = false; clearInterval(timer); };
  }, [aguardando, onView]);

  async function run(action: () => Promise<YouTubeView>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      { const parsed = parseYt(await action()); if (parsed) onView(parsed); }
    } catch (err) {
      setError(mensagem(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  async function enviarCliente(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      { const parsed = parseYt(await uploadYouTubeClient(await file.text())); if (parsed) onView(parsed); }
    } catch (err) {
      setError(mensagem(err, "Não foi possível enviar o cliente OAuth."));
    } finally {
      setBusy(false);
    }
  }

  async function conectar() {
    // Abre a janela já, dentro do clique; a URL do Google só chega depois.
    const popup = window.open("", "_blank");
    // A página do Google não precisa alcançar o painel que a abriu.
    if (popup) popup.opener = null;
    setBusy(true);
    setError(null);
    setLoginUrl(null);
    try {
      const next = await startYouTubeLogin();
      const url = next.login.url;
      if (url) {
        if (popup) popup.location.href = url;
        else setLoginUrl(url);
      }
      const parsed = parseYt(next);
      if (parsed) onView(parsed);
    } catch (err) {
      popup?.close();
      setError(mensagem(err, "Não foi possível iniciar o login do Google."));
    } finally {
      setBusy(false);
    }
  }

  function desconectar(id: string, titulo: string) {
    if (!window.confirm(`Desconectar o canal ${titulo}? O token local será apagado.`)) return;
    void run(() => disconnectChannel(id), "Não foi possível desconectar o canal.");
  }

  if (!view) return null;
  const selecionado = view.canais.find((c) => c.padrao)?.id ?? view.canais[0]?.id ?? null;
  const falhou = view.login.status === "falhou" && view.login.erro;

  return (
    <fieldset className="pub-publish-form">
      <legend className="pub-muted">Conta do YouTube</legend>
      {!view.cliente_configurado ? (
        <>
          <p className="pub-muted">
            Crie um cliente OAuth do tipo App para computador no Google Cloud (YouTube Data API v3 ativada) e envie o JSON baixado.
          </p>
          <label>
            Arquivo do cliente OAuth
            <input type="file" accept=".json,application/json" disabled={busy} onChange={(e) => void enviarCliente(e)} />
          </label>
        </>
      ) : (
        <>
          {view.canais.map((canal) => (
            <div key={canal.id} className="pub-canal">
              <label>
                <input
                  type="radio"
                  name="pub-canal"
                  checked={canal.id === selecionado}
                  disabled={busy}
                  onChange={() => void run(() => setDefaultChannel(canal.id), "Não foi possível trocar o canal.")}
                />
                {canal.thumbnail && (
                  <img src={canal.thumbnail} alt="" width={24} height={24} />
                )}
                {canal.titulo}
              </label>
              <button
                className="btn"
                type="button"
                aria-label={`Desconectar ${canal.titulo}`}
                disabled={busy}
                onClick={() => desconectar(canal.id, canal.titulo)}
              >
                Desconectar
              </button>
            </div>
          ))}
          <button className="btn" type="button" disabled={busy || aguardando} onClick={() => void conectar()}>
            {view.canais.length === 0 ? "Conectar conta Google" : "Adicionar canal"}
          </button>
          <p className="pub-muted">Contas com mais de um canal: o Google pede para escolher o canal no login.</p>
        </>
      )}
      {aguardando && <p role="status">Aguardando o login no Google… escolha o canal na tela do Google.</p>}
      {loginUrl && aguardando && (
        <a href={loginUrl} target="_blank" rel="noopener noreferrer">Abrir login do Google</a>
      )}
      {falhou && <p className="pub-warning" role="alert">{view.login.erro}</p>}
      {error && <p className="pub-warning" role="alert">{error}</p>}
    </fieldset>
  );
}

function PublishPanel({ runId, titulos }: { runId: string; titulos: string[] }) {
  const [view, setView] = React.useState<PublicacaoView | null>(null);
  const [loaded, setLoaded] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [chosen, setChosen] = React.useState<string | null>(null);
  const [agendar, setAgendar] = React.useState(false);
  const [quando, setQuando] = React.useState("");
  const [yt, setYt] = React.useState<YouTubeView | null>(null);
  const [ytError, setYtError] = React.useState<string | null>(null);
  const [loginUrl, setLoginUrl] = React.useState<string | null>(null);
  const loginAnterior = React.useRef<string | null>(null);

  React.useEffect(() => {
    let active = true;
    getYouTube()
      .then((value) => { if (active) setYt(parseYt(value)); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const loginStatus = yt?.login.status ?? null;
  React.useEffect(() => {
    // Login terminou: o backend pode ter passado a `conectado`.
    if (loginAnterior.current === "aguardando" && loginStatus !== "aguardando") {
      setLoginUrl(null);
      getPublication(runId)
        .then((value) => { const next = parseView(value); if (next) setView(next); })
        .catch(() => undefined);
    }
    loginAnterior.current = loginStatus;
  }, [loginStatus, runId]);

  React.useEffect(() => {
    let active = true;
    getPublication(runId)
      .then((value) => { if (active) setView(parseView(value)); })
      .catch(() => undefined)
      .finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [runId]);

  const emAndamento = view?.em_andamento === true;
  React.useEffect(() => {
    if (!emAndamento) return;
    let active = true;
    const timer = setInterval(() => {
      getPublication(runId)
        .then((value) => { if (active) { const next = parseView(value); if (next) setView(next); }; })
        .catch(() => undefined);
    }, POLL_MS);
    return () => { active = false; clearInterval(timer); };
  }, [runId, emAndamento]);

  const canalId = yt?.canais.find((c) => c.padrao)?.id ?? yt?.canais[0]?.id ?? null;

  async function enviar(titulo: string, publicarEm: string | null, canal: string | null = canalId) {
    setBusy(true);
    setError(null);
    try {
      setView(parseView(await publishRun(runId, { titulo, publicar_em: publicarEm, canal_id: canal })));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível enviar ao YouTube.");
    } finally {
      setBusy(false);
    }
  }

  const estado = view?.estado ?? null;
  const titulo = chosen && titulos.includes(chosen) ? chosen : titulos[0] ?? "";
  const quandoIso = agendar && quando && !Number.isNaN(new Date(quando).getTime()) ? new Date(quando).toISOString() : null;
  const podeEnviar = canalId !== null && !busy && titulo !== "" && (!agendar || quandoIso !== null);
  const alerta = error && <p className="pub-warning" role="alert">{error}</p>;

  const accountBlock = (
    <YouTubeAccount view={yt} onView={setYt} error={ytError} setError={setYtError} loginUrl={loginUrl} setLoginUrl={setLoginUrl} />
  );

  let body: React.ReactNode;
  if (!loaded) {
    body = <p className="pub-muted">Consultando o estado do envio…</p>;
  } else if (!view) {
    body = <p className="pub-muted">Estado do envio indisponível.</p>;
  } else if (view.em_andamento && (!estado || estado.etapa === "falhou")) {
    // A thread acabou de começar e ainda não gravou: nem formulário nem
    // "Tentar de novo", que só renderiam um 409 publication_running.
    body = <p>Iniciando envio…</p>;
  } else if (!estado) {
    body = (
      <>
        {accountBlock}
        <fieldset className="pub-publish-form">
          <legend className="pub-muted">Título</legend>
          {titulos.map((texto) => (
            <label key={texto}>
              <input type="radio" name="pub-titulo" checked={texto === titulo} onChange={() => setChosen(texto)} />
              {texto}
            </label>
          ))}
        </fieldset>
        <fieldset className="pub-publish-form">
          <legend className="pub-muted">Visibilidade</legend>
          <label><input type="radio" name="pub-quando" checked={!agendar} onChange={() => setAgendar(false)} />Privado</label>
          <label><input type="radio" name="pub-quando" checked={agendar} onChange={() => setAgendar(true)} />Agendar</label>
          {agendar && (
            <label>
              Data e hora
              <input type="datetime-local" value={quando} onChange={(event) => setQuando(event.target.value)} />
            </label>
          )}
        </fieldset>
        <p className="pub-muted">O vídeo sobe privado (ou agendado). Revise e libere no YouTube Studio.</p>
        <button className="btn btn-primary" type="button" disabled={!podeEnviar} onClick={() => enviar(titulo, quandoIso)}>
          Enviar ao YouTube
        </button>
        {alerta}
      </>
    );
  } else if (estado.etapa === "concluida") {
    body = (
      <>
        <p><b>Enviado ao YouTube</b></p>
        {estado.url && (
          <a className="btn btn-primary pub-download" href={estado.url} target="_blank" rel="noopener noreferrer">
            Abrir no YouTube Studio
          </a>
        )}
        {estado.canal_titulo && <p>Canal: {estado.canal_titulo}</p>}
        <p className="pub-muted">
          {estado.publicar_em ? `Agendado para ${new Date(estado.publicar_em).toLocaleString("pt-BR")}` : "Privado"}
        </p>
        {estado.avisos.length > 0 && <ul className="pub-avisos">{estado.avisos.map((aviso, i) => <li key={`${i}-${aviso}`}>{aviso}</li>)}</ul>}
        <p className="pub-muted">Fixe o comentário manualmente — a API do YouTube não fixa.</p>
      </>
    );
  } else if (estado.etapa === "falhou") {
    body = (
      <>
        <p className="pub-warning" role="note">Envio falhou{estado.erro ? `: ${estado.erro}` : "."}</p>
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => enviar(estado.titulo, estado.publicar_em, estado.canal_id ?? canalId)}>
          Tentar de novo
        </button>
        {alerta}
      </>
    );
  } else if (view.em_andamento) {
    const pct = estado.total_bytes > 0 ? Math.min(100, Math.floor((100 * estado.bytes_enviados) / estado.total_bytes)) : 0;
    body = estado.etapa === "enviando" ? (
      <>
        <p>Enviando vídeo… {pct}%</p>
        <div className="pub-progress" role="progressbar" aria-label="Progresso do envio" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <div className="pub-progress-bar" style={{ transform: `scaleX(${pct / 100})` }} />
        </div>
      </>
    ) : (
      <p>{estado.etapa === "thumbnail" ? "Enviando thumbnail…" : "Enviando legenda…"}</p>
    );
  } else {
    body = (
      <>
        <p>Envio interrompido.</p>
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => enviar(estado.titulo, estado.publicar_em, estado.canal_id ?? canalId)}>
          Retomar envio
        </button>
        {alerta}
      </>
    );
  }

  return (
    <Field title="Publicar no YouTube" headingId="pub-youtube">
      <div className="pub-publish">{body}</div>
      {estado?.etapa === "concluida" && estado.video_id && <DesempenhoPublicacao runId={runId} />}
    </Field>
  );
}

function PackageView({ artifact, state }: { artifact?: Artifact; state: EmbalagemState }) {
  const { data, loading, failed } = state;
  if (!artifact) return <Empty title="Embalagem ausente" detail="Esta execução não gerou títulos, descrição e tags." />;
  if (loading) return <Empty title="Abrindo embalagem" detail="Títulos e descrição aparecem assim que o arquivo carregar." />;
  if (failed || !data) return <Empty title="Embalagem indisponível" detail="O arquivo da embalagem não pôde ser lido." />;

  const titulos = (data.titulos ?? []).filter((titulo) => typeof titulo?.texto === "string");
  const descricao = typeof data.descricao === "string" ? data.descricao : "";
  const tags = (data.tags ?? []).filter((tag) => typeof tag === "string");
  const tagsTexto = tags.join(",");
  const comentario = typeof data.comentario_fixado === "string" ? data.comentario_fixado : "";

  return (
    <div className="pub-package">
      {data.capitulos_estimados === true && (
        <p className="pub-warning" role="note">
          Atenção: tempos dos capítulos são estimados; confira antes de publicar.
        </p>
      )}

      <Field title="Títulos" headingId="pub-titulos">
        {titulos.length === 0
          ? <p className="pub-muted">Nenhum título proposto.</p>
          : (
            <ol className="pub-titles">
              {titulos.map((titulo, index) => (
                <li key={`${index}-${titulo.texto}`}>
                  <div className="pub-title-text">
                    <b>{titulo.texto}</b>
                    {titulo.angulo && <small>{titulo.angulo}</small>}
                  </div>
                  <Counter
                    testId={`contador-titulo-${index + 1}`}
                    count={chars(titulo.texto)}
                    max={TITULO_MAXIMO}
                    recommended={TITULO_RECOMENDADO}
                    warnText="corta no celular"
                  />
                  <CopyButton label={`Copiar título ${index + 1}`} text={titulo.texto} />
                </li>
              ))}
            </ol>
          )}
      </Field>

      <Field
        title="Descrição"
        headingId="pub-descricao-h"
        actions={<><Counter testId="contador-descricao" count={chars(descricao)} max={DESCRICAO_MAXIMO} /><CopyButton label="Copiar descrição" text={descricao} /></>}
      >
        {descricao
          ? <pre className="pub-pre" data-testid="pub-descricao">{descricao}</pre>
          : <p className="pub-muted">Descrição vazia.</p>}
      </Field>

      <Field
        title="Tags"
        headingId="pub-tags"
        actions={<><Counter testId="contador-tags" count={chars(tagsTexto)} max={TAGS_MAXIMO} /><CopyButton label="Copiar tags" text={tagsTexto} /></>}
      >
        {tags.length
          ? <p className="pub-pre pub-tags">{tagsTexto}</p>
          : <p className="pub-muted">Nenhuma tag proposta.</p>}
      </Field>

      <Field
        title="Comentário fixado"
        headingId="pub-comentario"
        actions={comentario ? <CopyButton label="Copiar comentário fixado" text={comentario} /> : undefined}
      >
        {comentario
          ? <p className="pub-pre">{comentario}</p>
          : <p className="pub-muted">Sem comentário fixado.</p>}
      </Field>
    </div>
  );
}

function FilesView({ thumbnail, legenda, video }: { thumbnail?: Artifact; legenda?: Artifact; video?: Artifact }) {
  const [thumbFailed, setThumbFailed] = React.useState(false);
  return (
    <div className="pub-files">
      <Field
        title="Thumbnail"
        headingId="pub-thumb"
        actions={thumbnail ? <a className="btn" href={artifactDownloadUrl(thumbnail.id)} download={fileName(thumbnail)}>Baixar thumbnail</a> : undefined}
      >
        {!thumbnail
          ? <Empty title="Thumbnail ausente" detail="A etapa de imagens ainda não gerou a thumbnail." />
          : thumbFailed
            ? <Empty title="Thumbnail indisponível" detail="A prévia não pôde ser aberta; o download pode funcionar." />
            : <img className="pub-thumb" src={artifactContentUrl(thumbnail.id)} alt="Thumbnail do vídeo" onError={() => setThumbFailed(true)} />}
      </Field>

      <Field title="Vídeo final" headingId="pub-video">
        {video
          ? <a className="btn pub-download" href={artifactDownloadUrl(video.id)} download={fileName(video)}>Baixar vídeo</a>
          : <Empty title="Vídeo ausente" detail="A montagem ainda não produziu o vídeo final." />}
      </Field>

      <Field title="Legenda" headingId="pub-legenda">
        {legenda
          ? <a className="btn pub-download" href={artifactDownloadUrl(legenda.id)} download={fileName(legenda)}>Baixar legenda</a>
          : <Empty title="Legenda ausente" detail="A montagem ainda não gerou a legenda em português." />}
      </Field>
    </div>
  );
}

function Checklist({ runId }: { runId: string }) {
  const [checked, setChecked] = React.useState<Record<string, boolean>>({});
  React.useEffect(() => setChecked({}), [runId]);
  return (
    <section className="pub-field pub-checklist" aria-labelledby="pub-checklist-h">
      <div className="pub-field-head"><h3 id="pub-checklist-h">Conferência do upload</h3></div>
      <ul>
        {CHECKLIST.map((item) => (
          <li key={item.id}>
            <label>
              <input
                type="checkbox"
                checked={Boolean(checked[item.id])}
                onChange={(event) => setChecked((current) => ({ ...current, [item.id]: event.target.checked }))}
              />
              {item.label}
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Publication({ runs, loadArtifacts = listRunArtifacts }: PublicationProps) {
  const fallbackRunId = React.useMemo(() => defaultRunId(runs), [runs]);
  const [chosenRunId, setChosenRunId] = React.useState<string | null>(null);
  const runId = chosenRunId && runs.some((summary) => summary.run?.id === chosenRunId) ? chosenRunId : fallbackRunId;
  const [artifacts, setArtifacts] = React.useState<{ runId: string; items: Artifact[] } | null>(null);
  const [failedRunId, setFailedRunId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!runId) return;
    let active = true;
    setFailedRunId(null);
    loadArtifacts(runId)
      .then((items) => { if (active) setArtifacts({ runId, items: Array.isArray(items) ? items : [] }); })
      .catch(() => { if (active) setFailedRunId(runId); });
    return () => { active = false; };
  }, [runId, loadArtifacts]);

  const current = artifacts && artifacts.runId === runId ? artifacts.items : null;
  const embalagem = current ? latest(current, (a) => a.kind === "embalagem") : undefined;
  const thumbnail = current ? latest(current, (a) => a.kind === "thumbnail.jpg") : undefined;
  const legenda = current ? latest(current, (a) => a.kind === "legendas.srt") : undefined;
  const video = current ? latest(current, (a) => a.kind === "video/final.mp4") : undefined;
  const embalagemState = useEmbalagem(embalagem);
  const titulosEmbalagem = React.useMemo(
    () => (embalagemState.data?.titulos ?? []).map((t) => t?.texto).filter((t): t is string => typeof t === "string"),
    [embalagemState.data],
  );

  return (
    <main className="main">
      <PageHeader
        screen="publicacao"
        title="Publicação"
        description="Pacote de publicação da execução e envio ao YouTube."
        actions={runs.length > 0 && runId ? (
          <div className="pub-run-picker">
            <label htmlFor="pub-run-select">Execução</label>
            <select
              id="pub-run-select"
              className="select"
              value={runId}
              onChange={(event) => setChosenRunId(event.target.value)}
            >
              {runs.map((summary) => (
                <option key={summary.run.id} value={summary.run.id}>
                  {(summary.video?.tema || summary.run.id)} · {serviceStatusLabel(summary.run.status)}
                </option>
              ))}
            </select>
          </div>
        ) : undefined}
      />

      {!runId ? (
        <Empty title="Nenhuma execução concluída" detail="A embalagem aparece aqui quando uma execução terminar." />
      ) : failedRunId === runId ? (
        <Empty title="Arquivos indisponíveis" detail="Os arquivos desta execução não puderam ser carregados." />
      ) : !current ? (
        <Empty title="Abrindo execução" detail="Buscando os arquivos desta execução." />
      ) : (
        <div className="pub-layout" key={runId}>
          <PackageView artifact={embalagem} state={embalagemState} />
          <aside className="pub-side">
            <PublishPanel runId={runId} titulos={titulosEmbalagem} />
            <FilesView thumbnail={thumbnail} legenda={legenda} video={video} />
            <Checklist runId={runId} />
          </aside>
        </div>
      )}
    </main>
  );
}
