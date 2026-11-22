"use client";
import { useCallback, useState } from "react";
import { Atualizacao, Observacoes, SerieDiaria, useLeitura } from "./leitura-insights";
import { comConsulta, dataCivil, dataPublicacao, numero, somentePeriodo, type ListaVideos, type Resumo } from "../lib/insights";
import { IconArrowRight, IconProduction } from "./icons";

const medidas = [{id:"views", nome:"Visualizações"}, {id:"minutos", nome:"Minutos assistidos"}] as const;

function Comparacao({valor, anterior}:{valor:number|null;anterior:number|null|undefined}) {
  if (valor == null || anterior == null) return <small>Comparação indisponível</small>;
  if (anterior === 0) return <small>Período anterior · 0</small>;
  const variacao = (valor - anterior) / anterior;
  const rotulo = new Intl.NumberFormat("pt-BR", {style:"percent", signDisplay:"exceptZero", maximumFractionDigits:1}).format(variacao);
  return <small><b className={variacao > 0 ? "metric-up" : undefined}>{rotulo}</b> · anterior {numero(anterior)}</small>;
}

export function InsightsCanal({canal, consulta}:{canal:string;consulta:string}) {
  const [versao,setVersao] = useState(0);
  const atualizar = useCallback(()=>setVersao(n=>n+1),[]);
  const base = "/canais/"+encodeURIComponent(canal);
  const api = "/api"+base;
  const parametros = new URLSearchParams(consulta);
  const resumo = useLeitura<Resumo>(comConsulta(api+"/resumo",somentePeriodo(consulta)),versao);
  const lista = useLeitura<ListaVideos>(comConsulta(api+"/videos",consulta),versao);
  const dados = resumo.dados;
  const inicio = parametros.get("inicio") || dados?.inicio || "";
  const fim = parametros.get("fim") || dados?.fim || "";
  const persistidos = new URLSearchParams(consulta);
  if(inicio) persistidos.set("inicio",inicio);
  if(fim) persistidos.set("fim",fim);
  const query = persistidos.toString();
  const seguinte = new URLSearchParams(persistidos);
  if(lista.dados?.proximo_cursor) seguinte.set("cursor",lista.dados.proximo_cursor);

  const primeira = new URLSearchParams(persistidos);
  primeira.delete("cursor");
  const top = dados?.contribuicoes.filter(video => video.views != null)
    .sort((a,b) => b.views! - a.views!).slice(0,5) ?? [];

  return <main className="channel-page">
    <header className="insight-heading">
      <div><h1>Vídeos e insights</h1><p>Desempenho do canal e vídeos publicados.</p></div>
      <a className="btn" href={base + "/producao"}>Abrir produção <IconArrowRight size={15}/></a>
    </header>
    <div className="insight-toolbar">
    <form className="catalog-filters period-filters" action={base}>
      {["busca","ordem","publicado_de","publicado_ate"].map(k=>parametros.has(k) && <input key={k} type="hidden" name={k} value={parametros.get(k)!}/>)}
      <label>Início do período<input key={inicio} type="date" name="inicio" defaultValue={inicio} required/></label>
      <label>Fim do período<input key={fim} type="date" name="fim" defaultValue={fim} required/></label>
      <button className="btn" type="submit">Aplicar período</button>
    </form>
    <Atualizacao canal={canal} consulta={query} estado={dados?.estado} estadoCatalogo={dados?.estado_catalogo} ultima={dados?.ultima_atualizacao} atualizar={atualizar}/>
    </div>
    {(resumo.erro || lista.erro) && <div className="insight-alert" role="alert">{resumo.erro || lista.erro} <button className="btn" onClick={atualizar}>Tentar novamente</button></div>}
    {dados && <>
      <section className="panel insight-summary" aria-label="Resumo do período">
        <div className="insight-section-header"><h2>Resumo do período</h2>
          <span>{dataCivil(dados.inicio)} – {dataCivil(dados.fim)}</span></div>
        <div className="channel-metrics">
          {medidas.map(({id,nome}) => <div className="channel-metric" key={id}>
            <span>{nome}</span><strong>{numero(dados[id])}</strong>
            <Comparacao valor={dados[id]} anterior={dados.comparacao?.[id]}/>
          </div>)}
        </div>
      </section>
      <div className={top.length ? "insight-analysis with-ranking" : "insight-analysis"}>
        <SerieDiaria serie={dados.serie} inicio={dados.inicio} fim={dados.fim}/>
        {top.length > 0 && <section className="panel insight-ranking">
          <div className="insight-section-header"><h2>Mais vistos no período</h2></div>
          <ol>{top.map(video => <li key={video.video_id}>
            <a href={comConsulta(base+"/videos/"+encodeURIComponent(video.video_id),query)}>{video.titulo || "Vídeo " + video.video_id}</a>
            <span>{numero(video.views)} <small>visualizações</small></span>
          </li>)}</ol>
          {dados.amostra != null && <p>Amostra de {dados.amostra} vídeos</p>}
        </section>}
      </div>
    </>}
    <section className="panel channel-catalog">
      <div className="insight-section-header"><h2>Catálogo de vídeos</h2>
        {dados?.ultima_atualizacao_catalogo && <span>Catálogo atualizado em {new Date(dados.ultima_atualizacao_catalogo).toLocaleString("pt-BR")}</span>}
      </div>
      <form action={base} className="catalog-filters">
        {inicio && <input type="hidden" name="inicio" value={inicio}/>}
        {fim && <input type="hidden" name="fim" value={fim}/>}
        <label>Buscar título<input type="search" name="busca" defaultValue={parametros.get("busca") ?? ""}/></label>
        <label>Publicado de<input type="date" name="publicado_de" defaultValue={parametros.get("publicado_de") ?? ""}/></label>
        <label>Publicado até<input type="date" name="publicado_ate" defaultValue={parametros.get("publicado_ate") ?? ""}/></label>
        <label>Ordenar por<select name="ordem" defaultValue={parametros.get("ordem") || "data"}>
          <option value="data">Publicação recente</option><option value="resultado">Visualizações</option><option value="titulo">Título</option>
        </select></label>
        <button className="btn btn-primary" type="submit">Filtrar vídeos</button>
      </form>
      {lista.dados ? lista.dados.videos.length ? <div className="catalog-results">
        <div className="catalog-columns" aria-hidden="true"><span>Vídeo</span><span>Visualizações</span></div>
        <ul className="catalog-items">{lista.dados.videos.map(v=>
        <li key={v.video_id}>
          <a className="catalog-video" href={comConsulta(base+"/videos/"+encodeURIComponent(v.video_id),query)} aria-label={v.titulo}>
            {v.thumbnail ? <img alt="" loading="lazy" src={v.thumbnail}/> : <span className="catalog-placeholder" aria-hidden="true"><IconProduction size={22}/></span>}
            <span><b>{v.titulo}</b><small>{dataPublicacao(v.publicado_em)} · {v.run_id ? "Publicado pelo Forge" : "YouTube"}</small></span>
          </a>
          <span className="catalog-number"><b>{numero(v.views)}</b><small>visualizações</small></span>
        </li>)}</ul></div> : <p className="insight-empty">Nenhum vídeo encontrado.</p> : !lista.erro && <p className="insight-empty" role="status">Carregando catálogo…</p>}
      <div className="catalog-pagination">
        {parametros.has("cursor") && <a className="btn" href={comConsulta(base,primeira.toString())}>Primeira página</a>}
        {lista.dados?.proximo_cursor && <a className="btn" href={comConsulta(base,seguinte.toString())}>Próxima página</a>}
      </div>
    </section>
    {dados && <section className="panel evidence-list"><h2>Fontes e cobertura</h2>
      <Observacoes itens={dados.observacoes} base={base} consulta={query}/>
    </section>}
  </main>;
}
