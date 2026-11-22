import type { Observacao } from "./insights";

export interface PautaInicial {
  titulo: string;
  tema: string;
  pergunta: string;
  recorte: string;
  promessa: string;
}

export interface PautaBoard extends PautaInicial {
  abertura: string;
  blocos: string[];
  desfecho: string;
  perguntas_pesquisa: string[];
  referencias: string[];
}

export type CampoPauta = keyof PautaBoard;
export type ValorCampo = string | string[];

export const pautaVazia: PautaBoard = {
  titulo: "", tema: "", pergunta: "", recorte: "", promessa: "",
  abertura: "", blocos: [], desfecho: "", perguntas_pesquisa: [], referencias: [],
};

export interface DefinicaoCampo {
  chave: CampoPauta;
  rotulo: string;
  limite: number;
  lista?: "itens" | "linhas";
}

export const camposPauta: DefinicaoCampo[] = [
  {chave: "titulo", rotulo: "Título provisório", limite: 200},
  {chave: "tema", rotulo: "Tema", limite: 200},
  {chave: "pergunta", rotulo: "Público e pergunta central", limite: 1200},
  {chave: "recorte", rotulo: "Recorte", limite: 1200},
  {chave: "promessa", rotulo: "Promessa", limite: 1200},
  {chave: "abertura", rotulo: "Abertura", limite: 1200},
  {chave: "blocos", rotulo: "Sequência de blocos", limite: 1200, lista: "itens"},
  {chave: "desfecho", rotulo: "Desfecho", limite: 1200},
  {chave: "perguntas_pesquisa", rotulo: "Perguntas de pesquisa", limite: 200, lista: "linhas"},
  {chave: "referencias", rotulo: "Referências", limite: 200, lista: "linhas"},
];

export const rotuloCampo = (campo: CampoPauta) => camposPauta.find(c => c.chave === campo)?.rotulo ?? campo;

export function completarPauta(pauta: Partial<PautaBoard> | null | undefined): PautaBoard {
  return {...pautaVazia, ...(pauta ?? {})};
}

export function mesmoValor(a: ValorCampo | undefined, b: ValorCampo | undefined) {
  return JSON.stringify(a ?? "") === JSON.stringify(b ?? "");
}

/** O servidor apara os textos e descarta itens vazios das listas; comparar sempre a forma normalizada. */
export function normalizarPauta(pauta: PautaBoard): PautaBoard {
  const limpar = (itens: string[]) => itens.map(item => item.trim()).filter(Boolean);
  const textos = Object.fromEntries(camposPauta.filter(campo => !campo.lista)
    .map(({chave}) => [chave, (pauta[chave] as string).trim()]));
  return {...pauta, ...textos, blocos: limpar(pauta.blocos), perguntas_pesquisa: limpar(pauta.perguntas_pesquisa),
    referencias: limpar(pauta.referencias)};
}

export function mesmaPauta(a: PautaBoard | null, b: PautaBoard | null) {
  return camposPauta.every(({chave}) => mesmoValor(completarPauta(a)[chave], completarPauta(b)[chave]));
}

export function pautaPreenchida(pauta: PautaBoard) {
  return Object.values(pauta).some(valor => Array.isArray(valor) ? valor.some(item => item.trim()) : valor.trim());
}

export interface AlteracaoCampo {
  campo: CampoPauta;
  anterior: ValorCampo;
  valor: ValorCampo;
}

export interface MensagemBoard {
  id: string;
  autor: "criador" | "ia";
  texto: string;
  criada_em: string;
  base_revisao: number | null;
  alteracoes: AlteracaoCampo[];
  aplicadas: string[];
}

export interface FluxoBoard {
  id: string;
  nome: string;
  descricao: string;
  disponivel: boolean;
  motivo: string | null;
}

export interface JanelaEpisodio {
  completa: boolean;
  fim: string;
  observacoes: Observacao[];
}

export interface EpisodioBoard {
  aprovacao_id: string;
  revisao: number;
  titulo: string;
  run_id: string;
  run_status: string | null;
  momento: "em_producao" | "cancelado" | "enviado" | "agendado" | "publico" | "janela_completa";
  publicar_em: string | null;
  video_id: string | null;
  publicado_em: string | null;
  janelas: {d7: JanelaEpisodio; d28: JanelaEpisodio} | null;
  abertura: string;
  promessa: string;
  url: string | null;
}

export interface Pendencia {
  campo: string;
  mensagem: string;
}

export interface FonteBoard {
  id: string;
  tipo: "catalogo" | "desempenho" | "comentario" | "episodio";
  titulo: string;
  url: string;
  texto: string | null;
  publicado_em: string | null;
  observacao: Observacao | null;
  amostra: number | null;
}

export interface IdeiaBoard {
  id: string;
  tipo: "continuacao" | "publico" | "experimento";
  pauta: PautaInicial;
  hipotese: boolean;
  diferenca: string;
  justificativa: string;
  referencias: FonteBoard[];
  motivo_descarte: string | null;
}

export interface Board {
  revisao: number;
  posicionamento: string;
  propostas: IdeiaBoard[];
  guardadas: IdeiaBoard[];
  candidata: IdeiaBoard | null;
  pauta: PautaBoard | null;
  origem_pauta: IdeiaBoard | null;
  analisado_em: string | null;
  erro: "analise_indisponivel" | null;
  operacao: "sugestoes" | "combinacao" | "conversa" | null;
  fluxo_id: string | null;
  conversa: MensagemBoard[];
  fluxos: FluxoBoard[];
  pendencias: Pendencia[];
  ultima_aprovacao?: {id: string; run_id: string; revisao: number; titulo: string} | null;
  episodios?: EpisodioBoard[];
  contexto: {
    precisa_posicionamento: boolean;
    aguardando: boolean;
    estado_catalogo: string;
    estado_analytics: string;
    atualizado_em: string | null;
    observacoes: FonteBoard[];
  };
}

export type ComandoBoard =
  | {acao: "posicionamento"; texto: string}
  | {acao: "pauta"; pauta: PautaBoard}
  | {acao: "desenvolver" | "guardar"; ideia_id: string}
  | {acao: "descartar"; ideia_id: string; motivo: string}
  | {acao: "fluxo"; fluxo_id: string}
  | {acao: "remover_guardada"; ideia_id: string}
  | {acao: "aplicar_sugestao"; mensagem_id: string; campos: CampoPauta[]};

export type PedidoBoard =
  | {tipo: "sugestoes"; atualizar?: boolean}
  | {tipo: "combinacao"; ideias: string[]}
  | {tipo: "conversa"; mensagem: string};
