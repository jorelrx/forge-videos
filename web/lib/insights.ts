export interface VideoCatalogo {
  video_id: string; titulo: string; thumbnail: string | null;
  publicado_em: string | null; views: number | null; run_id: string | null;
}
export interface Observacao {
  medida: string; valor: number | null; unidade: string; origem: string;
  inicio: string; fim: string; inicio_efetivo: string | null; fim_efetivo: string | null;
  cobertura: number | null; preferida?: boolean; lido_em: string; video_id: string | null; evidencia: string;
  denominador?: string | number | null;
}
export interface Dia { dia: string; views: number | null; minutos: number | null }
interface Leitura {
  inicio: string; fim: string; estado: string; ultima_atualizacao: string | null;
  serie: Dia[]; observacoes: Observacao[];
}
export interface Resumo extends Leitura {
  ultima_atualizacao_catalogo?: string | null;
  estado_catalogo: string; views: number | null; minutos: number | null;
  comparacao: {views: number | null; minutos: number | null} | null;
  contribuicoes: {video_id:string;titulo?:string;views:number | null}[];
  amostra: number | string | null;
}
export interface Detalhe extends Leitura {
  video: VideoCatalogo;
  retencao: {posicao:number;proporcao:number}[];
  janelas: {d7: Observacao[]; d28: Observacao[]};
}
export interface ListaVideos { videos: VideoCatalogo[]; proximo_cursor: string | null }

export const numero = (v: number | null | undefined) => v == null ? "Indisponível" : v.toLocaleString("pt-BR",{maximumFractionDigits:2});
export const dataCivil = (v: string | null) => v ? v.slice(0,10).split("-").reverse().join("/") : "Data indisponível";
export function dataPublicacao(data: string | null) {
  return data && data.includes("T") ? new Date(data).toLocaleDateString("pt-BR",{timeZone:"America/Los_Angeles"}) : dataCivil(data);
}
export function consultaPagina(params: Record<string, string | string[] | undefined>) {
  const resultado = new URLSearchParams();
  for (const [k,v] of Object.entries(params)) if (typeof v === "string" && v) resultado.set(k,v);
  return resultado.toString();
}
export function somentePeriodo(consulta: string) {
  const todos = new URLSearchParams(consulta);
  const periodo = new URLSearchParams();
  for (const chave of ["inicio","fim"]) if(todos.get(chave)) periodo.set(chave,todos.get(chave)!);
  return periodo.toString();
}
export function comConsulta(path:string,consulta:string) { return consulta ? path+"?"+consulta : path; }
