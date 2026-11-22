"use client";
import { useCallback, useState } from "react";
import { Atualizacao, Observacoes, SerieDiaria, useLeitura } from "./leitura-insights";
import { comConsulta, dataPublicacao, numero, somentePeriodo, type ListaVideos, type Resumo } from "../lib/insights";

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

  return <main className="channel-page">
    <h1>Vídeos e insights</h1>
    <form className="catalog-filters" action={base}>
      {["busca","ordem","publicado_de","publicado_ate"].map(k=>parametros.has(k) && <input key={k} type="hidden" name={k} value={parametros.get(k)!}/>)}
      <label>Início do período<input key={inicio} type="date" name="inicio" defaultValue={inicio} required/></label>
      <label>Fim do período<input key={fim} type="date" name="fim" defaultValue={fim} required/></label>
      <button className="btn" type="submit">Aplicar período</button>
    </form>
    <Atualizacao canal={canal} consulta={query} estado={dados?.estado} estadoCatalogo={dados?.estado_catalogo} ultima={dados?.ultima_atualizacao} atualizar={atualizar}/>
    {(resumo.erro || lista.erro) && <div role="alert">{resumo.erro || lista.erro} <button className="btn" onClick={atualizar}>Tentar novamente</button></div>}
    {dados && <>
      <div className="channel-metrics">
        {[["Visualizações",dados.views,dados.comparacao?.views],["Tempo de exibição (min)",dados.minutos,dados.comparacao?.minutos]].map(([nome,valor,anterior])=>
          <a className="channel-metric" href={nome === "Visualizações" ? "#views" : "#minutos"} onClick={()=>{const item=document.getElementById(nome === "Visualizações" ? "views" : "minutos");if(item instanceof HTMLDetailsElement)item.open=true;}} key={nome}><span>{nome}</span><strong>{numero(valor as number|null)}</strong>
            {anterior != null && <small>Período anterior · {numero(anterior as number)}</small>}</a>)}
      </div>
      <SerieDiaria serie={dados.serie}/>
      <section className="evidence-list"><h2>Evidências do período</h2>
        <Observacoes itens={dados.observacoes} base={base} consulta={query}/>
        {dados.contribuicoes.length>0 && <section><h3>Contribuição por vídeo</h3>
          {dados.amostra != null && <p>Amostra · {dados.amostra}</p>}
          <ul>{dados.contribuicoes.map(v=><li key={v.video_id}><a href={comConsulta(base+"/videos/"+encodeURIComponent(v.video_id),query)}>{v.video_id}</a> · {numero(v.views)} visualizações</li>)}</ul>
        </section>}
      </section>
    </>}
    <section className="channel-catalog"><h2>Catálogo de vídeos</h2>
      {dados?.ultima_atualizacao_catalogo && <p>Última atualização do catálogo · {new Date(dados.ultima_atualizacao_catalogo).toLocaleString("pt-BR")}</p>}
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
      {lista.dados ? lista.dados.videos.length ? <ul className="catalog-items">{lista.dados.videos.map(v=>
        <li key={v.video_id}>
          {v.thumbnail ? <img alt="" loading="lazy" src={v.thumbnail}/> : <span className="catalog-placeholder" aria-hidden="true">▶</span>}
          <div><a href={comConsulta(base+"/videos/"+encodeURIComponent(v.video_id),query)}>{v.titulo}</a><small>{dataPublicacao(v.publicado_em)}</small></div>
          <span><b>{numero(v.views)}</b><small>visualizações</small></span>
        </li>)}</ul> : <p>Nenhum vídeo encontrado.</p> : !lista.erro && <p role="status">Carregando catálogo…</p>}
      <div className="catalog-pagination">
        {parametros.has("cursor") && <a className="btn" href={comConsulta(base,primeira.toString())}>Primeira página</a>}
        {lista.dados?.proximo_cursor && <a className="btn" href={comConsulta(base,seguinte.toString())}>Próxima página</a>}
      </div>
    </section>
  </main>;
}
