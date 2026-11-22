import Link from "next/link";
import type { FonteBoard, IdeiaBoard } from "../lib/board-criativo";
import { nomes } from "./leitura-insights";
import { dataCivil, numero } from "../lib/insights";

export function FonteEditorial({fonte}: {fonte: FonteBoard}) {
  const obs = fonte.observacao;
  const externa = fonte.tipo === "comentario";
  return <div className="board-source">
    {externa ? <a href={fonte.url} target="_blank" rel="noreferrer">Comentário em {fonte.titulo}</a>
      : <Link href={fonte.url}>{fonte.titulo}</Link>}
    {fonte.texto && <blockquote>{fonte.texto}</blockquote>}
    {!obs && fonte.publicado_em && <time dateTime={fonte.publicado_em}>{dataCivil(fonte.publicado_em)}</time>}
    {obs && <dl>
      <div><dt>Medida</dt><dd>{nomes[obs.medida] ?? obs.medida} · {numero(obs.valor)} {obs.unidade}</dd></div>
      <div><dt>Período</dt><dd>{dataCivil(obs.inicio)} a {dataCivil(obs.fim)}</dd></div>
      <div><dt>Origem</dt><dd>{obs.origem}</dd></div>
      <div><dt>Cobertura</dt><dd>{obs.cobertura == null ? "Sem confirmação por dia" : obs.cobertura + " dias"}</dd></div>
      {fonte.amostra != null && <div><dt>Amostra</dt><dd>{fonte.amostra} vídeos</dd></div>}
    </dl>}
  </div>;
}

export function CorpoIdeia({ideia}: {ideia: IdeiaBoard}) {
  const {pauta} = ideia;
  const categoria = ideia.tipo === "continuacao" ? "Continuação de tema" :
    ideia.tipo === "experimento" ? "Experimento editorial" : ideia.hipotese ? "Pergunta editorial" : "Pergunta do público";
  return <>
    <div className="board-card-labels"><span>{categoria}</span>{ideia.hipotese && <small>Hipótese</small>}</div>
    <h3>{pauta.titulo}</h3>
    <p className="board-question">{pauta.pergunta}</p>
    <dl className="board-angle">
      <div><dt>Recorte</dt><dd>{pauta.recorte}</dd></div>
      <div><dt>Diferença para o catálogo</dt><dd>{ideia.diferenca}</dd></div>
    </dl>
    <details className="evidence-panel board-evidence">
      <summary>Justificativa e fontes</summary>
      <p>{ideia.justificativa}</p>
      {ideia.referencias.map(fonte => <FonteEditorial key={fonte.id} fonte={fonte}/>)}
      {ideia.referencias.length === 0 && <p>Sem fonte observada para esta ideia.</p>}
    </details>
  </>;
}
