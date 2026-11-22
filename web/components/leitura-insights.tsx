"use client";
import { useEffect, useState } from "react";
import { ApiError, studioRequest } from "../lib/api";
import { comConsulta, dataCivil, numero, somentePeriodo, type Dia, type Observacao } from "../lib/insights";
import { VinculoCanal } from "./vinculo-canal";
import { IconRefresh } from "./icons";

export function useLeitura<T>(url: string, versao: number) {
  const [resposta,setResposta] = useState<{url:string;dados:T} | null>(null);
  const [falha,setFalha] = useState<{url:string;mensagem:string;codigo?:string} | null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    studioRequest<T>(url,{signal:controller.signal}).then(dados=>{
      if(!controller.signal.aborted) {setResposta({url,dados});setFalha(null);}
    }).catch(e=>{
      if(controller.signal.aborted) return;
      const erroApi = e instanceof ApiError ? e.failure : undefined;
      if (erroApi && ([401,403,404].includes(erroApi.status) || erroApi.code === "cursor_desatualizado")) setResposta(null);
      setFalha({url,mensagem:e instanceof Error ? e.message : "Falha temporária de leitura.",codigo:erroApi?.code});
    });
    return ()=>controller.abort();
  },[url,versao]);
  const falhaAtual = falha?.url === url ? falha : null;
  return {dados:resposta?.url === url ? resposta.dados : null, erro:falhaAtual?.mensagem ?? "", codigoErro:falhaAtual?.codigo};
}

const estados: Record<string,string> = {
  sincronizando:"Sincronização em andamento.",sem_autorizacao:"Autorize o acesso aos indicadores do YouTube.",
  sem_dados:"Sem dados no período.",canal_vazio:"Nenhum vídeo público neste canal.",atrasado:"A fonte ainda não cobriu todo o período.",
  falha_temporaria:"Falha temporária ao atualizar o histórico.",reconectar:"A conexão com o YouTube precisa ser renovada.",
  api_desativada:"Ative a YouTube Analytics API no projeto Google Cloud para carregar os indicadores do período.",
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
    <button className="btn" onClick={sincronizar} disabled={enviando || pendente}><IconRefresh size={15}/>{enviando || pendente ? "Atualizando…" : "Atualizar histórico"}</button>
    {[...new Set([estado,estadoCatalogo])].map(s=>s && estados[s] && <span key={s} role="status">{estados[s]}</span>)}
    {estado === "sem_autorizacao" && <VinculoCanal canalId={canal} analytics onComplete={atualizar}/>}
    {estado === "api_desativada" && <a href="https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com" target="_blank" rel="noreferrer">Abrir configuração no Google Cloud</a>}
    {(estado === "reconectar" || estadoCatalogo === "reconectar") && <VinculoCanal canalId={canal} onComplete={atualizar}/>}
    {erro && <span role="alert">{erro}</span>}
  </div>;
}

export function SerieDiaria({serie, inicio, fim}:{serie:Dia[];inicio:string;fim:string}) {
  const [medida, setMedida] = useState<"views" | "minutos">("views");
  const pontos = serie.filter(dia => dia[medida] !== null);
  const maximo = Math.max(0, ...pontos.map(dia => dia[medida]!));
  const primeiro = Date.parse(inicio);
  const ultimo = Date.parse(fim);
  const totalDias = (ultimo - primeiro) / 86400000 + 1;
  // Intervalos longos seguem legíveis na tabela, sem comprimir centenas de barras.
  const desenhar = pontos.length > 0 && totalDias >= 1 && totalDias <= 93;
  const valores = new Map(serie.map(dia => [dia.dia, dia[medida]]));

  return <section className="panel insight-trend" aria-label="Evolução diária">
    <div className="insight-section-header">
      <h2>Evolução diária</h2>
      {serie.length > 0 && <div className="metric-toggle" role="group" aria-label="Medida do gráfico">
        <button type="button" aria-pressed={medida === "views"} onClick={() => setMedida("views")}>Visualizações</button>
        <button type="button" aria-pressed={medida === "minutos"} onClick={() => setMedida("minutos")}>Minutos assistidos</button>
      </div>}
    </div>
    {desenhar && <div className="trend-figure">
      <div className="trend-scale" aria-hidden="true"><span>{numero(maximo)}</span><span>0</span></div>
      <div className="trend-bars" aria-hidden="true">
        {Array.from({length: totalDias}, (_, indice) => {
          const dia = new Date(primeiro + indice * 86400000).toISOString().slice(0,10);
          const valor = valores.get(dia);
          return <div className="trend-day" key={dia} title={dataCivil(dia) + " · " + numero(valor)}>
            {valor != null && <span className="trend-bar" style={{height: (maximo ? valor / maximo * 100 : 0) + "%"}}/>}
          </div>;
        })}
      </div>
      <div className="trend-dates"><time dateTime={inicio}>{dataCivil(inicio)}</time><time dateTime={fim}>{dataCivil(fim)}</time></div>
    </div>}
    {serie.length > 0 ? <details className="evidence-panel" open={!desenhar && pontos.length > 0}>
      <summary>Dados por dia · {serie.length} {serie.length === 1 ? "dia" : "dias"} com registro</summary>
      <table><thead><tr><th scope="col">Dia</th><th scope="col">Visualizações</th><th scope="col">Minutos assistidos</th></tr></thead>
        <tbody>{serie.map(d=><tr key={d.dia}><th scope="row">{dataCivil(d.dia)}</th><td>{numero(d.views)}</td><td>{numero(d.minutos)}</td></tr>)}</tbody></table>
    </details> : <p className="insight-empty">A fonte ainda não retornou dados diários para este período.</p>}
  </section>;
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
