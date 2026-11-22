"use client";
import { useCallback, useState } from "react";
import { Atualizacao, nomes, Observacoes, SerieDiaria, useLeitura } from "./leitura-insights";
import { comConsulta, dataCivil, dataPublicacao, numero, somentePeriodo, type Detalhe } from "../lib/insights";

export function InsightsVideo({canal,videoId,consulta}:{canal:string;videoId:string;consulta:string}) {
  const [versao,setVersao] = useState(0);
  const atualizar = useCallback(()=>setVersao(n=>n+1),[]);
  const base = "/canais/"+encodeURIComponent(canal);
  const caminho = base+"/videos/"+encodeURIComponent(videoId);
  const {dados,erro} = useLeitura<Detalhe>(comConsulta("/api"+caminho,somentePeriodo(consulta)),versao);
  return <main className="channel-page">
    <a className="insight-back" href={comConsulta(base,consulta)}>Voltar ao catálogo</a>
    {erro && <div className="insight-alert" role="alert">{erro} <button className="btn" onClick={atualizar}>Tentar novamente</button></div>}
    {dados ? <>
      <header className="episode-header">
        {dados.video.thumbnail && <img alt="" src={dados.video.thumbnail}/>}
        <div><h1>{dados.video.titulo}</h1>
          <p>Publicado em {dataPublicacao(dados.video.publicado_em)}</p>
          <a className="btn" href={"https://www.youtube.com/watch?v=" + encodeURIComponent(videoId)} target="_blank" rel="noreferrer">Ver no YouTube</a>
        </div>
      </header>
      <div className="insight-toolbar">
        <Atualizacao canal={canal} consulta={consulta} videoId={videoId} estado={dados.estado} ultima={dados.ultima_atualizacao} atualizar={atualizar}/>
      </div>
      <section className="panel insight-summary">
        <div className="insight-section-header"><h2>Desempenho do episódio</h2>
          {dados.inicio && dados.fim && <span>{dataCivil(dados.inicio)} – {dataCivil(dados.fim)}</span>}</div>
        {dados.observacoes.length > 0 ? <dl className="episode-metrics">
          {dados.observacoes.map(o => <div key={o.medida} className="channel-metric">
            <dt>{nomes[o.medida] ?? o.medida.replaceAll("_"," ")}</dt>
            <dd><strong>{numero(o.valor)}</strong>{o.valor != null && <small>{o.unidade}</small>}</dd>
          </div>)}
        </dl> : <p className="insight-empty">Indicadores indisponíveis neste período.</p>}
      </section>
      <SerieDiaria serie={dados.serie} inicio={dados.inicio} fim={dados.fim}/>
      <section className="panel insight-retention">
        <div className="insight-section-header"><h2>Retenção de público</h2></div>
        {dados.retencao.length > 0 ? <details className="evidence-panel"><summary>Retenção por posição no vídeo</summary>
          <table><thead><tr><th scope="col">Posição no vídeo</th><th scope="col">Retenção</th></tr></thead>
            <tbody>{dados.retencao.map(p=><tr key={p.posicao}><td>{numero(p.posicao*100)}%</td><td>{numero(p.proporcao*100)}%</td></tr>)}</tbody>
          </table></details> : <p className="insight-empty">A fonte ainda não disponibilizou a curva de retenção.</p>}
      </section>
      <section className="panel insight-windows">
        <div className="insight-section-header"><h2>Desde a publicação</h2></div>
        <div className="episode-windows">{(["d7","d28"] as const).map(j=><div key={j}>
          <h3>{j === "d7" ? "Primeiros 7 dias" : "Primeiros 28 dias"}</h3>
          <Observacoes grupo={j} itens={dados.janelas[j]} base={base} consulta={consulta}/>
        </div>)}</div>
      </section>
      {dados.observacoes.length > 0 && <section className="panel evidence-list"><h2>Fontes e cobertura</h2>
        <Observacoes itens={dados.observacoes} base={base} consulta={consulta}/>
      </section>}
    </> : !erro && <p role="status">Carregando episódio…</p>}
  </main>;
}
