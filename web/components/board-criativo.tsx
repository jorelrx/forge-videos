"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBoardCriativo } from "../hooks/use-board-criativo";
import { pautaVazia, type IdeiaBoard, type PautaBoard } from "../lib/board-criativo";
import { CorpoIdeia, FonteEditorial } from "./board-ideia";
import { EditorPauta, RevisarPauta } from "./board-pauta";
import { Atualizacao } from "./leitura-insights";

export function BoardCriativo({canal}: {canal: string}) {
  return <BoardCanal key={canal} canal={canal}/>;
}

function FormPosicionamento({atual, aberto, ocupado, salvar}: {
  atual: string; aberto: boolean; ocupado: boolean; salvar: (texto: string) => void;
}) {
  function enviar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const texto = String(new FormData(event.currentTarget).get("posicionamento") ?? "").trim();
    if (texto) salvar(texto);
  }

  return <details className="panel board-position" open={aberto || undefined}>
    <summary>Posicionamento editorial</summary>
    <form className="board-form" onSubmit={enviar}>
      <label>Sobre o que é o canal e para quem você faz vídeos?
        <textarea rows={3} name="posicionamento" maxLength={1200} defaultValue={atual} required/>
      </label>
      <button type="submit" className="btn btn-primary" disabled={ocupado}>Salvar posicionamento</button>
    </form>
  </details>;
}

function DescartarIdeia({salvar, ocupado}: {salvar: (motivo: string) => void; ocupado: boolean}) {
  function enviar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    salvar(String(new FormData(event.currentTarget).get("motivo") ?? "").trim());
  }

  return <details className="board-discard">
    <summary>Descartar</summary>
    <form className="board-form" onSubmit={enviar}>
      <label>Motivo (opcional)<input name="motivo" maxLength={200}/></label>
      <button type="submit" className="btn" disabled={ocupado}>Confirmar descarte</button>
    </form>
  </details>;
}

function BoardCanal({canal}: {canal: string}) {
  const {board, falhaLeitura, falhaAcao, ocupado, enviar, carregar, recarregarRevisao} = useBoardCriativo(canal);
  const [manual, setManual] = useState(false);
  const [editando, setEditando] = useState<PautaBoard | null>(null);
  const [revisando, setRevisando] = useState<IdeiaBoard | null>(null);
  const [selecao, setSelecao] = useState<string[]>([]);
  const tentouInicial = useRef(false);
  const base = "/canais/" + encodeURIComponent(canal);

  useEffect(() => {
    if (!board || board.operacao || board.erro || ocupado || board.propostas.length || board.pauta
      || board.contexto.aguardando || (board.contexto.precisa_posicionamento && !board.posicionamento)
      || tentouInicial.current) return;
    tentouInicial.current = true;
    void enviar({tipo: "sugestoes"}, board.revisao);
  }, [board, ocupado, enviar]);

  if (!board) return <main className="channel-page board-page">
    <h1>Próximo vídeo</h1>
    {falhaLeitura ? <div role="alert" className="insight-alert">
      {falhaLeitura} <button className="btn" type="button" onClick={carregar}>Tentar novamente</button>
    </div> : <p role="status">Carregando rascunho…</p>}
  </main>;

  const contexto = board.contexto;
  const candidatas = board.propostas.filter(ideia => ideia.motivo_descarte == null);
  const disponiveis = new Set([...candidatas, ...board.guardadas].map(ideia => ideia.id));
  const selecionadas = selecao.filter(id => disponiveis.has(id));
  const guardadas = new Set(board.guardadas.map(ideia => ideia.id));
  const podeAnalisar = !contexto.aguardando && (!contexto.precisa_posicionamento || !!board.posicionamento);
  const podeEditar = !ocupado;
  const pauta = editando ?? board.pauta;

  async function desenvolver(ideia: IdeiaBoard) {
    if (!board) return;
    if (await enviar({acao: "desenvolver", ideia_id: ideia.id}, board.revisao)) {
      setRevisando(null);
      setEditando(null);
      setManual(true);
    }
  }

  function escolher(ideia: IdeiaBoard) {
    if (pauta && Object.values(pauta).some(valor => valor.trim())) setRevisando(ideia);
    else void desenvolver(ideia);
  }

  function marcar(id: string) {
    setSelecao(selecionadas.includes(id) ? selecionadas.filter(item => item !== id) : [...selecionadas, id]);
  }

  function controleSelecao(ideia: IdeiaBoard) {
    return <label className="board-check">
      <input type="checkbox" checked={selecionadas.includes(ideia.id)}
        disabled={ocupado || !!board?.operacao || (selecionadas.length >= 2 && !selecionadas.includes(ideia.id))}
        onChange={() => marcar(ideia.id)}/>
      Combinar <span className="sr-only">{ideia.pauta.titulo}</span>
    </label>;
  }

  return <main className="channel-page board-page">
    <header className="insight-heading">
      <div><h1>Próximo vídeo</h1><p>Escolha um recorte para começar a pauta do canal.</p></div>
      <Link className="btn" href={base}>Vídeos e insights</Link>
    </header>
    <section className="panel board-context" aria-label="Histórico do canal">
      <h2>Histórico do canal</h2>
      <Atualizacao canal={canal} consulta="" estado={contexto.estado_analytics}
        estadoCatalogo={contexto.estado_catalogo} ultima={contexto.atualizado_em} atualizar={carregar}/>
      {contexto.observacoes.length > 0 && <details className="evidence-panel">
        <summary>Observações do período</summary>
        {contexto.observacoes.map(fonte => <FonteEditorial key={fonte.id} fonte={fonte}/>)}
      </details>}
    </section>

    {(falhaAcao || falhaLeitura) && <div className="insight-alert" role="alert">
      {falhaAcao?.mensagem || falhaLeitura}
      {falhaAcao?.conflito && <button type="button" className="btn" onClick={recarregarRevisao}>Carregar revisão atual</button>}
    </div>}
    <FormPosicionamento key={board.posicionamento} atual={board.posicionamento} aberto={contexto.precisa_posicionamento && !board.posicionamento}
      ocupado={ocupado} salvar={texto => void enviar({acao: "posicionamento", texto}, board.revisao)}/>

    <section className="board-proposals" aria-labelledby="board-proposals-title">
      <div className="insight-section-header">
        <div><h2 id="board-proposals-title">Propostas</h2>
          {board.analisado_em && <small>Análise de {new Date(board.analisado_em).toLocaleString("pt-BR")}</small>}
        </div>
        <div className="board-actions">
          {podeAnalisar &&
            <button className="btn" disabled={ocupado || !!board.operacao} type="button"
              onClick={() => void enviar({tipo: "sugestoes", atualizar: board.propostas.length > 0}, board.revisao)}>
              {board.erro ? "Tentar análise novamente" : board.propostas.length ? "Gerar novas propostas" : "Gerar propostas"}
            </button>}
          {selecionadas.length > 0 && <button className="btn" type="button"
            disabled={selecionadas.length !== 2 || ocupado || !!board.operacao}
            onClick={() => void enviar({tipo: "combinacao", ideias: selecionadas}, board.revisao)}>
            Combinar ideias ({selecionadas.length}/2)
          </button>}
        </div>
      </div>
      {board.operacao && <p role="status">{board.operacao === "combinacao" ? "Combinando ideias…" : "Preparando sugestões…"}</p>}
      {board.erro && <p role="status">A IA não concluiu a análise. Você pode continuar com a pauta manual.</p>}
      {contexto.aguardando && !board.propostas.length && <p role="status">Aguardando a primeira leitura do histórico…</p>}
      {contexto.precisa_posicionamento && !board.posicionamento && !contexto.aguardando &&
        <p>Informe o posicionamento para receber três hipóteses para o canal.</p>}
      {candidatas.length > 0 && <div className="board-card-grid">
        {candidatas.map(ideia => <article key={ideia.id} className="panel board-card" data-tipo={ideia.tipo}>
          <CorpoIdeia ideia={ideia}/>
          <div className="board-actions">
            <button className="btn btn-primary" type="button" disabled={!podeEditar} onClick={() => escolher(ideia)}>Desenvolver</button>
            <button className="btn" type="button" disabled={!podeEditar || guardadas.has(ideia.id)}
              onClick={() => void enviar({acao: "guardar", ideia_id: ideia.id}, board.revisao)}>
              {guardadas.has(ideia.id) ? "Guardada" : "Guardar"}
            </button>
          </div>
          {controleSelecao(ideia)}
          <DescartarIdeia ocupado={ocupado} salvar={motivo => void enviar({acao: "descartar", ideia_id: ideia.id, motivo}, board.revisao)}/>
        </article>)}
      </div>}
      {board.propostas.length > 0 && candidatas.length === 0 && <p>Todas as propostas desta análise foram descartadas.</p>}
    </section>

    {board.candidata && board.candidata.id !== board.origem_pauta?.id && <article className="panel board-card">
      <h2>Proposta combinada</h2>
      <CorpoIdeia ideia={board.candidata}/>
      <button className="btn btn-primary" type="button" disabled={ocupado}
        onClick={() => escolher(board.candidata!)}>Usar proposta combinada</button>
    </article>}
    {revisando && pauta && <RevisarPauta atual={pauta} ideia={revisando} ocupado={ocupado}
      aplicar={() => void desenvolver(revisando)} cancelar={() => setRevisando(null)}/>}

    <section className="panel board-pauta" aria-labelledby="board-pauta-title">
      <div className="insight-section-header"><h2 id="board-pauta-title">Pauta inicial</h2>
        {board.pauta && <small>Revisão {board.revisao}</small>}
      </div>
      {manual || pauta ? <EditorPauta pauta={pauta ?? pautaVazia} onChange={setEditando} ocupado={ocupado}
        onSave={async () => {
          if (await enviar({acao: "pauta", pauta: pauta ?? pautaVazia}, board.revisao)) setEditando(null);
        }}/> : <button className="btn" type="button" onClick={() => setManual(true)}>Abrir pauta manual</button>}
    </section>

    <section className="panel board-saved" aria-labelledby="board-saved-title">
      <h2 id="board-saved-title">Ideias guardadas</h2>
      {board.guardadas.length ? <ul>
        {board.guardadas.map(ideia => <li key={ideia.id}>
          <details className="evidence-panel"><summary>{ideia.pauta.titulo}</summary>
            <CorpoIdeia ideia={ideia}/>
          </details>
          <div className="board-actions">
            <button className="btn" type="button" disabled={!podeEditar} onClick={() => escolher(ideia)}>Desenvolver ideia guardada</button>
            {!candidatas.some(candidata => candidata.id === ideia.id) && controleSelecao(ideia)}
          </div>
        </li>)}
      </ul> : <p>Guarde uma proposta para retomá-la em outro episódio.</p>}
    </section>
  </main>;
}
