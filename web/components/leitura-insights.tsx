"use client";
import { useEffect, useState } from "react";
import { ApiError, studioRequest } from "../lib/api";
import { comConsulta, dataCivil, numero, somentePeriodo, type Dia, type Observacao } from "../lib/insights";
import { VinculoCanal } from "./vinculo-canal";

export function useLeitura<T>(url: string, versao: number) {
  const [resposta,setResposta] = useState<{url:string;dados:T} | null>(null);
  const [falha,setFalha] = useState<{url:string;mensagem:string} | null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    studioRequest<T>(url,{signal:controller.signal}).then(dados=>{
      if(!controller.signal.aborted) {setResposta({url,dados});setFalha(null);}
    }).catch(e=>{
      if(controller.signal.aborted) return;
      if(e instanceof ApiError && [401,403,404].includes(e.failure.status)) setResposta(null);
      setFalha({url,mensagem:e instanceof Error ? e.message : "Falha temporária de leitura."});
    });
    return ()=>controller.abort();
  },[url,versao]);
  return {dados:resposta?.url === url ? resposta.dados : null, erro:falha?.url === url ? falha.mensagem : ""};
}

const estados: Record<string,string> = {
  sincronizando:"Sincronização em andamento.",sem_autorizacao:"Autorize o acesso aos indicadores do YouTube.",
  sem_dados:"Sem dados no período.",canal_vazio:"Nenhum vídeo público neste canal.",atrasado:"A fonte ainda não cobriu todo o período.",
  falha_temporaria:"Falha temporária ao atualizar o histórico.",reconectar:"A conexão com o YouTube precisa ser renovada.",
};

export function Atualizacao({canal,consulta,estado,estadoCatalogo,ultima,atualizar,videoId}:{
  canal:string;consulta:string;videoId?:string;estado?:string;estadoCatalogo?:string;ultima?:string|null;atualizar:()=>void;
}) {
  const [erro,setErro] = useState("");
  const [enviando,setEnviando] = useState(false);
  const pendente = estado === "sincronizando" || estadoCatalogo === "sincronizando";
  useEffect(()=>{
    if(!pendente) return;
    const timer=window.setInterval(atualizar,3500);
    return ()=>window.clearInterval(timer);
  },[pendente,atualizar]);
  async function sincronizar(){
    setEnviando(true);setErro("");
    try {
      const params = new URLSearchParams(somentePeriodo(consulta));
      if (videoId) params.set("video_id",videoId);
      await studioRequest(comConsulta("/api/canais/"+encodeURIComponent(canal)+"/sincronizacoes",params.toString()),{method:"POST"});
      atualizar();
    } catch(e){setErro(e instanceof Error ? e.message : "Falha ao iniciar sincronização.");}
    finally {setEnviando(false);}
  }
  return <div className="reading-status">
    <span>{ultima ? "Última atualização válida · "+new Date(ultima).toLocaleString("pt-BR") : "Ainda sem leitura confirmada"}</span>
    <button className="btn" onClick={sincronizar} disabled={enviando || pendente}>Atualizar histórico</button>
    {[...new Set([estado,estadoCatalogo])].map(s=>s && estados[s] && <span key={s} role="status">{estados[s]}</span>)}
    {estado === "sem_autorizacao" && <VinculoCanal canalId={canal} analytics/>}
    {(estado === "reconectar" || estadoCatalogo === "reconectar") && <VinculoCanal canalId={canal}/>}
    {erro && <span role="alert">{erro}</span>}
  </div>;
}

export function SerieDiaria({serie}:{serie:Dia[]}) {
  return <details className="evidence-panel"><summary>Evolução diária</summary>
    {serie.length ? <table><thead><tr><th>Dia</th><th>Visualizações</th><th>Minutos assistidos</th></tr></thead>
      <tbody>{serie.map(d=><tr key={d.dia}><td>{dataCivil(d.dia)}</td><td>{numero(d.views)}</td><td>{numero(d.minutos)}</td></tr>)}</tbody></table>
      : <p>Série diária indisponível.</p>}
  </details>;
}

export const nomes: Record<string,string> = {visualizacoes:"Visualizações",views:"Visualizações",minutos:"Tempo de exibição",minutos_assistidos:"Tempo de exibição",duracao_media:"Duração média",percentual_assistido:"Percentual assistido"};

export function Observacoes({itens,base,consulta,grupo}:{grupo?:string;itens:Observacao[];base:string;consulta:string}) {
  return <div className="observations">{itens.length === 0 && <p>Nenhuma observação disponível.</p>}
    {itens.map((o,i)=><details id={[grupo,o.medida,itens.findIndex(item=>item.medida===o.medida)===i ? "" : i].filter(Boolean).join("-")} key={i} className="evidence-panel"><summary>{nomes[o.medida] ?? o.medida.replaceAll("_"," ")} · {numero(o.valor)}</summary>
      <dl>{Object.entries({"Unidade":o.unidade,"Fonte":o.origem,"Janela":dataCivil(o.inicio)+" – "+dataCivil(o.fim),
        "Intervalo observado":o.inicio_efetivo && o.fim_efetivo ? dataCivil(o.inicio_efetivo)+" – "+dataCivil(o.fim_efetivo) : "Indisponível",
        "Cobertura":o.cobertura == null ? "Indisponível" : o.cobertura+" dias","Denominador":o.denominador,"Leitura":o.lido_em && new Date(o.lido_em).toLocaleString("pt-BR")})
        .filter(([,v])=>v!=null).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {o.video_id && <a href={comConsulta(base+"/videos/"+encodeURIComponent(o.video_id),consulta)}>Episódio {o.video_id}</a>}
      {o.evidencia?.startsWith(base+"?") || o.evidencia?.startsWith(base+"/videos/") ? <a href={o.evidencia}>Abrir evidência</a> : null}
    </details>)}
  </div>;
}
