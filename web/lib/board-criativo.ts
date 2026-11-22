import type { Observacao } from "./insights";

export interface PautaBoard {
  titulo: string;
  tema: string;
  pergunta: string;
  recorte: string;
  promessa: string;
}

export const pautaVazia: PautaBoard = {titulo: "", tema: "", pergunta: "", recorte: "", promessa: ""};

export const camposPauta: {chave: keyof PautaBoard; rotulo: string; limite: number}[] = [
  {chave: "titulo", rotulo: "Título provisório", limite: 200},
  {chave: "tema", rotulo: "Tema", limite: 200},
  {chave: "pergunta", rotulo: "Pergunta central", limite: 1200},
  {chave: "recorte", rotulo: "Recorte", limite: 1200},
  {chave: "promessa", rotulo: "Promessa", limite: 1200},
];

export interface FonteBoard {
  id: string;
  tipo: "catalogo" | "desempenho" | "comentario";
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
  pauta: PautaBoard;
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
  operacao: "sugestoes" | "combinacao" | null;
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
  | {acao: "descartar"; ideia_id: string; motivo: string};

export type PedidoBoard =
  | {tipo: "sugestoes"; atualizar?: boolean}
  | {tipo: "combinacao"; ideias: string[]};
