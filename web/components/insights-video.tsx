"use client";
import { useCallback, useState } from "react";
import { Atualizacao, Observacoes, SerieDiaria, useLeitura } from "./leitura-insights";
import { comConsulta, dataCivil, dataPublicacao, numero, somentePeriodo, type Detalhe } from "../lib/insights";

export function InsightsVideo({canal,videoId,consulta}:{canal:string;videoId:string;consulta:string}) {
  const [versao,setVersao] = useState(0);
  const atualizar = useCallback(()=>setVersao(n=>n+1),[]);
  const base = "/canais/"+encodeURIComponent(canal);
  const caminho = base+"/videos/"+encodeURIComponent(videoId);
  const {dados,erro} = useLeitura<Detalhe>(comConsulta("/api"+caminho,somentePeriodo(consulta)),versao);
  return <main className="channel-page">
    <a href={comConsulta(base,consulta)}>Voltar ao catálogo</a>
    {erro && <div role="alert">{erro} <button className="btn" onClick={atualizar}>Tentar novamente</button></div>}
    {dados ? <>
      <h1>{dados.video.titulo}</h1>
      <p>Publicado em {dataPublicacao(dados.video.publicado_em)} · {dataCivil(dados.inicio)} – {dataCivil(dados.fim)}</p>
      <Atualizacao canal={canal} consulta={consulta} videoId={videoId} estado={dados.estado} ultima={dados.ultima_atualizacao} atualizar={atualizar}/>
      <SerieDiaria serie={dados.serie}/>
      <section><h2>Indicadores do episódio</h2><Observacoes itens={dados.observacoes} base={base} consulta={consulta}/></section>
      <details className="evidence-panel"><summary>Retenção de público</summary>
        {dados.retencao.length ? <table><thead><tr><th>Posição no vídeo</th><th>Retenção</th></tr></thead>
          <tbody>{dados.retencao.map(p=><tr key={p.posicao}><td>{numero(p.posicao*100)}%</td><td>{numero(p.proporcao*100)}%</td></tr>)}</tbody></table>
          : <p>Curva de retenção indisponível.</p>}
      </details>
      {(["d7","d28"] as const).map(j=><section key={j}><h2>{j === "d7" ? "D+7" : "D+28"}</h2>
        <Observacoes grupo={j} itens={dados.janelas[j]} base={base} consulta={consulta}/>
      </section>)}
    </> : !erro && <p role="status">Carregando episódio…</p>}
  </main>;
}
