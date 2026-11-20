"use client";

/* eslint-disable jsx-a11y/media-has-caption -- O áudio mostra a transcrição do trecho ao lado; a API ainda não fornece VTT, e o vídeo final expõe o roteiro na aba própria. */

import React from "react";
import { artifactContentUrl } from "../lib/api";
import type { Artifact, RunView, StageName, WorkItem } from "../lib/contracts";

type OutputTab = "roteiro" | "audios" | "imagens" | "video";

const TABS: { id: OutputTab; label: string }[] = [
  { id: "roteiro", label: "Roteiro" },
  { id: "audios", label: "Áudios" },
  { id: "imagens", label: "Imagens" },
  { id: "video", label: "Vídeo" },
];

type ScriptBlock = {
  texto: string;
  referencias?: string[];
  referencias_legadas?: string[];
  citacoes_literais?: { path: string; trecho: string }[];
};

type ScriptSection = {
  nome: string;
  conteudo: string;
  blocos?: ScriptBlock[];
};

type ScriptDocument = {
  tema?: string;
  tese?: string;
  secoes?: ScriptSection[];
  fontes?: { path?: string; titulo: string; autor?: string | null }[];
};

const REF_MARKER = /\[([A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+|\d+(?:\.\d+)*(?:\.f\d+)?)\]/g;

function artifactType(artifact: Artifact): OutputTab | null {
  if (artifact.relative_path === "roteiro.md" || artifact.relative_path === "video/roteiro.json" || artifact.kind.startsWith("roteiro")) return "roteiro";
  if (artifact.mime_type.startsWith("audio/")) return "audios";
  if (artifact.mime_type.startsWith("image/")) return "imagens";
  if (artifact.mime_type.startsWith("video/")) return "video";
  return null;
}

function stageItems(run: RunView, stage: StageName): WorkItem[] {
  return run.stages?.[stage]?.items ?? [];
}

function stageStatus(run: RunView, stage: StageName): string {
  return run.stages?.[stage]?.stage_run?.status ?? "pending";
}

function statusText(status: string): string {
  const labels: Record<string, string> = {
    succeeded: "Pronto", running: "Gerando", pending: "Aguardando",
    failed: "Falhou", interrupted: "Interrompido", invalidated: "Aguardando nova geração",
    paused: "Pausado", pausing: "Pausando",
  };
  return labels[status] ?? "Aguardando";
}

function stageHint(run: RunView, stage: StageName): string {
  if (run.run.status === "failed") return "A execução parou antes desta saída ficar pronta.";
  const status = stageStatus(run, stage);
  if (status === "failed") return "Esta etapa falhou. O que já foi produzido continua disponível.";
  if (["running", "pausing"].includes(status)) return "Novas saídas aparecem aqui durante a geração.";
  if (status === "succeeded") return "Etapa concluída.";
  return "Esta etapa ainda não começou.";
}

function visibleText(content: string): { text: string; refs: string[] } {
  const refs = [...content.matchAll(REF_MARKER)].map((match) => match[1]);
  const text = content
    .replace(REF_MARKER, "")
    .split(/\r?\n/)
    .filter((line) => !/^\s*\([^)]*\)\s*$/.test(line))
    .join("\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
  return { text, refs: [...new Set(refs)] };
}

function itemStatus(item: WorkItem | undefined, artifact: Artifact | undefined, stage: string): string {
  if (artifact) return "succeeded";
  return item?.status ?? stage;
}

function referencesFor(blocks: ScriptBlock[], fallback: string[]): { paths: string[]; legacy: string[]; quotes: { path: string; trecho: string }[] } {
  const paths = [...new Set(blocks.flatMap((block) => block.referencias ?? []))];
  const legacy = [...new Set([
    ...fallback,
    ...blocks.flatMap((block) => block.referencias_legadas ?? []),
  ])];
  const quotes = blocks.flatMap((block) => block.citacoes_literais ?? []);
  return { paths, legacy, quotes };
}

function ScriptView({ run, artifact }: { run: RunView; artifact?: Artifact }) {
  const [document, setDocument] = React.useState<ScriptDocument | null>(null);
  const [error, setError] = React.useState(false);
  const [loading, setLoading] = React.useState(Boolean(artifact));
  const artifactId = artifact?.id;
  const artifactMime = artifact?.mime_type;

  React.useEffect(() => {
    if (!artifactId || !artifactMime) {
      setDocument(null);
      setError(false);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    fetch(artifactContentUrl(artifactId), { cache: "no-store", signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("artifact_unavailable");
        return response.text();
      })
      .then((raw) => {
        if (controller.signal.aborted) return;
        const parsed = artifactMime === "application/json"
          ? JSON.parse(raw) as ScriptDocument
          : parseMarkdownScript(raw);
        setDocument(parsed);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        if (controller.signal.aborted) return;
        setError(true);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [artifactId, artifactMime]);

  if (!artifact && !document) {
    return <OutputEmpty title="Roteiro aguardando" detail={stageHint(run, "roteiro")} />;
  }
  if (loading) return <OutputEmpty title="Abrindo roteiro" detail="O texto aparece assim que o arquivo fica disponível." />;
  if (error || !document) return <OutputEmpty title="Roteiro indisponível" detail="O arquivo desta execução não pôde ser carregado." />;

  const fontes = new Map((document.fontes ?? []).filter((source) => source.path).map((source) => [source.path!, source]));
  return (
    <div className="script-output">
      {document.tese && <p className="script-thesis">{document.tese}</p>}
      {(document.secoes ?? []).map((section, index) => {
        const blocks = section.blocos ?? [];
        const clean = visibleText(section.conteudo ?? "");
        const narration = blocks.length
          ? blocks.map((block) => block.texto).join(" ")
          : clean.text;
        const refs = referencesFor(blocks, clean.refs);
        return (
          <article className="script-section" key={`${section.nome}-${index}`}>
            <header><span>{String(index + 1).padStart(2, "0")}</span><h3>{section.nome}</h3></header>
            {narration && <p>{narration}</p>}
            {(refs.paths.length > 0 || refs.legacy.length > 0 || refs.quotes.length > 0) && (
              <details className="source-details">
                <summary>Referências · {refs.paths.length + refs.legacy.length + refs.quotes.length}</summary>
                <ul>
                  {refs.paths.map((path) => {
                    const source = fontes.get(path);
                    return <li key={path}><code>{path}</code>{source && <span>{source.autor ? `${source.autor} · ` : ""}{source.titulo}</span>}</li>;
                  })}
                  {refs.legacy.map((path) => {
                    const source = fontes.get(path);
                    return <li key={`legacy-${path}`}><small>Marcador antigo · não verificado</small><code>{path}</code>{source && <span>{source.autor ? `${source.autor} · ` : ""}{source.titulo}</span>}</li>;
                  })}
                  {refs.quotes.map((quote, quoteIndex) => <li key={`${quote.path}-${quoteIndex}`}><code>{quote.path}</code><span>“{quote.trecho}”</span></li>)}
                </ul>
              </details>
            )}
          </article>
        );
      })}
    </div>
  );
}

function parseMarkdownScript(raw: string): ScriptDocument {
  const sections = raw.split(/^##\s+/m).slice(1).map((part) => {
    const newline = part.indexOf("\n");
    return {
      nome: (newline < 0 ? part : part.slice(0, newline)).trim(),
      conteudo: newline < 0 ? "" : part.slice(newline + 1).trim(),
    };
  });
  return { secoes: sections };
}

function OutputEmpty({ title, detail }: { title: string; detail: string }) {
  return <div className="output-empty"><span aria-hidden="true">◇</span><h3>{title}</h3><p>{detail}</p></div>;
}

function AudioOutputs({ run, artifacts }: { run: RunView; artifacts: Artifact[] }) {
  const items = stageItems(run, "audio");
  const byWorkItem = new Map(artifacts.filter((item) => item.work_item_id).map((item) => [item.work_item_id!, item]));
  const [selectedItem, setSelectedItem] = React.useState<string | null>(null);
  const [mediaError, setMediaError] = React.useState<string | null>(null);
  const selected = items.find((item) => item.item_key === selectedItem) ?? items.find((item) => byWorkItem.has(item.id));
  const selectedArtifact = selected
    ? byWorkItem.get(selected.id)
    : artifacts.find((artifact) => artifact.relative_path === selectedItem) ?? artifacts[0];
  const text = typeof selected?.input.texto === "string" ? visibleText(selected.input.texto).text : "";

  if (items.length === 0 && artifacts.length === 0) return <OutputEmpty title="Áudios aguardando" detail={stageHint(run, "audio")} />;
  return (
    <div className="media-output">
      <div className="output-index" aria-label="Trechos de áudio">
        {items.map((item) => {
          const audio = byWorkItem.get(item.id);
          return (
            <button type="button" key={item.id} className={`output-index-item ${selected?.id === item.id ? "selected" : ""}`} onClick={() => { setSelectedItem(item.item_key); setMediaError(null); }} aria-pressed={selected?.id === item.id}>
              <span className="output-index-mark">{audio ? "♫" : "·"}</span>
              <span><b>{item.item_key}</b><small>{typeof item.input.secao === "string" ? item.input.secao : "Trecho"}</small></span>
              <em>{statusText(itemStatus(item, audio, stageStatus(run, "audio")))}</em>
            </button>
          );
        })}
        {items.length === 0 && artifacts.map((audio) => (
          <button type="button" key={audio.id} className={`output-index-item ${selectedArtifact?.id === audio.id ? "selected" : ""}`} onClick={() => { setSelectedItem(audio.relative_path); setMediaError(null); }}>
            <span className="output-index-mark">♫</span><span><b>{audio.relative_path.split("/").pop()}</b><small>Áudio registrado</small></span><em>Pronto</em>
          </button>
        ))}
      </div>
      <div className="output-detail">
        {selectedArtifact ? (
          <>
            <div className="output-detail-heading"><div><small>{selected?.item_key ?? selectedArtifact.relative_path.split("/").pop()}</small><h3>{selected && typeof selected.input.secao === "string" ? selected.input.secao : "Narração"}</h3></div><span className="output-ready">Pronto</span></div>
            {text && <p className="spoken-text">{text}</p>}
            {mediaError === selectedArtifact.id
              ? <div className="media-unavailable">Arquivo de áudio indisponível.</div>
              : <audio key={selectedArtifact.id} aria-label={`Áudio ${selected?.item_key ?? "selecionado"}`} controls preload="metadata" src={artifactContentUrl(selectedArtifact.id)} onError={() => setMediaError(selectedArtifact.id)} />}
            {selected && ((Array.isArray(selected.input.referencias) && selected.input.referencias.length > 0) || (Array.isArray(selected.input.referencias_legadas) && selected.input.referencias_legadas.length > 0)) && (
              <details className="source-details"><summary>Referências deste trecho</summary><ul>
                {Array.isArray(selected.input.referencias) && selected.input.referencias.map((path) => <li key={String(path)}><code>{String(path)}</code></li>)}
                {Array.isArray(selected.input.referencias_legadas) && selected.input.referencias_legadas.map((path) => <li key={`legacy-${String(path)}`}><small>Marcador antigo · não verificado</small><code>{String(path)}</code></li>)}
              </ul></details>
            )}
          </>
        ) : <OutputEmpty title="Trecho ainda sem áudio" detail={stageHint(run, "audio")} />}
      </div>
    </div>
  );
}

function ImageOutputs({ run, artifacts }: { run: RunView; artifacts: Artifact[] }) {
  const items = stageItems(run, "imagens");
  const byWorkItem = new Map(artifacts.filter((item) => item.work_item_id).map((item) => [item.work_item_id!, item]));
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState<string | null>(null);
  const selected = items.find((item) => item.id === selectedId) ?? items.find((item) => byWorkItem.has(item.id));
  const selectedArtifact = selected
    ? byWorkItem.get(selected.id)
    : artifacts.find((artifact) => artifact.id === selectedId) ?? artifacts[0];
  if (items.length === 0 && artifacts.length === 0) return <OutputEmpty title="Imagens aguardando" detail={stageHint(run, "imagens")} />;
  return (
    <div className="media-output">
      <div className="output-index" aria-label="Imagens da execução">
        {items.length > 0 ? items.map((item) => {
          const image = byWorkItem.get(item.id);
          const prompt = typeof item.input.prompt === "string" ? item.input.prompt : "Beat visual";
          return <button type="button" key={item.id} className={`output-index-item ${selected?.id === item.id ? "selected" : ""}`} onClick={() => { setSelectedId(item.id); setFailed(null); }} aria-pressed={selected?.id === item.id}><span className="output-index-mark">▧</span><span><b>{item.item_key}</b><small>{prompt}</small></span><em>{statusText(itemStatus(item, image, stageStatus(run, "imagens")))}</em></button>;
        }) : artifacts.map((image) => <button type="button" key={image.id} className={`output-index-item ${selectedArtifact?.id === image.id ? "selected" : ""}`} onClick={() => { setSelectedId(image.id); setFailed(null); }} aria-pressed={selectedArtifact?.id === image.id}><span className="output-index-mark">▧</span><span><b>{image.relative_path.split("/").pop()}</b><small>Imagem registrada</small></span><em>Pronto</em></button>)}
      </div>
      <div className="output-detail image-detail">
        {selectedArtifact && failed !== selectedArtifact.id
          ? <img key={selectedArtifact.id} src={artifactContentUrl(selectedArtifact.id)} alt={selected && typeof selected.input.prompt === "string" ? selected.input.prompt : "Imagem gerada"} onError={() => setFailed(selectedArtifact.id)} />
          : <OutputEmpty title={failed ? "Imagem indisponível" : "Imagem aguardando"} detail={failed ? "A prévia não pôde ser aberta." : stageHint(run, "imagens")} />}
        {selectedArtifact && selected && <p>{typeof selected.input.prompt === "string" ? selected.input.prompt : selectedArtifact.relative_path}</p>}
      </div>
    </div>
  );
}

function VideoOutputs({ run, artifact }: { run: RunView; artifact?: Artifact }) {
  const [failed, setFailed] = React.useState(false);
  if (!artifact) return <OutputEmpty title="Vídeo aguardando" detail={stageHint(run, "montagem")} />;
  return failed
    ? <OutputEmpty title="Vídeo indisponível" detail="O arquivo final não pôde ser aberto." />
    : <div className="video-output"><video key={artifact.id} aria-label="Vídeo final; roteiro e trechos de áudio disponíveis nas outras abas" controls preload="metadata" src={artifactContentUrl(artifact.id)} onError={() => setFailed(true)} /><p>{artifact.relative_path.split("/").pop()} · {Math.round(artifact.size_bytes / 1024 / 1024 * 10) / 10} MB. Roteiro e trechos de fala disponíveis nas outras abas.</p></div>;
}

export function RunOutputs({ run }: { run: RunView }) {
  const [tab, setTab] = React.useState<OutputTab>("roteiro");
  const artifacts = React.useMemo(
    () => (run.artifacts ?? []).filter((artifact) => artifact.run_id === run.run.id && artifact.is_current),
    [run.artifacts, run.run.id],
  );
  const grouped = React.useMemo(() => {
    const result: Record<OutputTab, Artifact[]> = { roteiro: [], audios: [], imagens: [], video: [] };
    for (const artifact of artifacts) {
      const type = artifactType(artifact);
      if (type) result[type].push(artifact);
    }
    return result;
  }, [artifacts]);
  const scriptArtifact = grouped.roteiro.find((item) => item.relative_path === "video/roteiro.json")
    ?? grouped.roteiro.find((item) => item.relative_path === "roteiro.md")
    ?? grouped.roteiro[0];
  const finalVideo = grouped.video.find((item) => item.relative_path === "video/final.mp4") ?? grouped.video[0];

  return (
    <section className="run-outputs" aria-label="Saídas da execução">
      <header className="run-outputs-head"><div><span>ARQUIVOS DESTA EXECUÇÃO</span><h2>Saídas</h2></div><small>{artifacts.length} disponíveis</small></header>
      <div className="output-tabs" role="tablist" aria-label="Tipos de saída">
        {TABS.map((item) => {
          const count = item.id === "audios" ? grouped.audios.length : item.id === "imagens" ? grouped.imagens.length : item.id === "video" ? grouped.video.length : grouped.roteiro.length;
          return <button key={item.id} id={`output-tab-${item.id}`} role="tab" type="button" aria-selected={tab === item.id} aria-controls="output-tabpanel" onClick={() => setTab(item.id)}>{item.label}<span>{count}</span></button>;
        })}
      </div>
      <div id="output-tabpanel" role="tabpanel" aria-labelledby={`output-tab-${tab}`} className="output-panel">
        {tab === "roteiro" && <ScriptView run={run} artifact={scriptArtifact} />}
        {tab === "audios" && <AudioOutputs run={run} artifacts={grouped.audios} />}
        {tab === "imagens" && <ImageOutputs run={run} artifacts={grouped.imagens} />}
        {tab === "video" && <VideoOutputs run={run} artifact={finalVideo} />}
      </div>
    </section>
  );
}
