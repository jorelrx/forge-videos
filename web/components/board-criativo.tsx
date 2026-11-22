"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useBoardCriativo } from "../hooks/use-board-criativo";
import {
  completarPauta, mesmaPauta, normalizarPauta, pautaPreenchida, pautaVazia, type CampoPauta, type IdeiaBoard,
  type PautaBoard,
} from "../lib/board-criativo";
import { ConversaBoard } from "./board-conversa";
import { EpisodiosBoard } from "./board-episodios";
import { DecisaoPauta } from "./board-decisao";
import { CorpoIdeia, FonteEditorial } from "./board-ideia";
import { ConflitoPauta, EditorPauta, RevisarPauta } from "./board-pauta";
import { Atualizacao } from "./leitura-insights";

const ATRASO_AUTOSAVE = 1200;

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
  const {board, falhaLeitura, falhaAcao, ocupado, enviar, carregar, recarregarRevisao, salvarPauta, salvarAoSair, aprovar}
    = useBoardCriativo(canal);
  const router = useRouter();
  const pedidoAprovacao = useRef<{revisao: number; fluxo: string} | null>(null);
  const [manual, setManual] = useState(false);
  const [editando, setEditando] = useState<PautaBoard | null>(null);
  const [conflito, setConflito] = useState(false);
  const [situacao, setSituacao] = useState("");
  const [revisando, setRevisando] = useState<IdeiaBoard | null>(null);
  const [selecao, setSelecao] = useState<string[]>([]);
  const [aba, setAba] = useState<"pauta" | "conversa">("pauta");
  const tentouInicial = useRef(false);
  const base = useRef<PautaBoard | null>(null);
  const local = useRef<PautaBoard | null>(null);
  local.current = editando;
  const salva = board?.pauta ? completarPauta(board.pauta) : null;
  const pendente = !!editando && !mesmaPauta(normalizarPauta(editando), salva);
  const pendenteRef = useRef(false);
  pendenteRef.current = pendente && !conflito;
  const baseUrl = "/canais/" + encodeURIComponent(canal);

  useEffect(() => {
    if (!board || board.operacao || board.erro || ocupado || board.propostas.length || board.pauta
      || board.contexto.aguardando || (board.contexto.precisa_posicionamento && !board.posicionamento)
      || tentouInicial.current) return;
    tentouInicial.current = true;
    void enviar({tipo: "sugestoes"}, board.revisao);
  }, [board, ocupado, enviar]);

  const salvar = useCallback(async () => {
    const enviado = local.current;
    if (!enviado) return "erro";
    setSituacao("Salvando…");
    const resultado = await salvarPauta(normalizarPauta(enviado), base.current);
    if (resultado.estado === "salvo") {
      base.current = completarPauta(resultado.board.pauta);
      setSituacao("Alterações salvas");
    } else if (resultado.estado === "conflito") {
      setConflito(true);
      setSituacao("");
    } else {
      setSituacao(resultado.estado === "ocupado" ? "Alterações não salvas" : "Falha ao salvar");
    }
    return resultado.estado;
  }, [salvarPauta]);

  useEffect(() => {
    if (!pendente || conflito || ocupado) return;
    const timer = window.setTimeout(() => void salvar(), ATRASO_AUTOSAVE);
    return () => window.clearTimeout(timer);
  }, [editando, pendente, conflito, ocupado, salvar]);

  useEffect(() => {
    function sair() {
      if (pendenteRef.current && local.current) salvarAoSair(normalizarPauta(local.current), base.current);
    }
    const oculto = () => { if (document.visibilityState === "hidden") sair(); };
    window.addEventListener("pagehide", sair);
    document.addEventListener("visibilitychange", oculto);
    return () => {
      window.removeEventListener("pagehide", sair);
      document.removeEventListener("visibilitychange", oculto);
    };
  }, [salvarAoSair]);

  if (!board) return <main className="channel-page board-page">
    <h1>Próximo vídeo</h1>
    {falhaLeitura ? <div role="alert" className="insight-alert">
      {falhaLeitura} <button className="btn" type="button" onClick={() => void carregar()}>Tentar novamente</button>
    </div> : <p role="status">Carregando rascunho…</p>}
  </main>;

  const contexto = board.contexto;
  const conversa = board.conversa ?? [];
  const candidatas = board.propostas.filter(ideia => ideia.motivo_descarte == null);
  const disponiveis = new Set([...candidatas, ...board.guardadas].map(ideia => ideia.id));
  const selecionadas = selecao.filter(id => disponiveis.has(id));
  const guardadas = new Set(board.guardadas.map(ideia => ideia.id));
  const podeAnalisar = !contexto.aguardando && (!contexto.precisa_posicionamento || !!board.posicionamento);
  const podeEditar = !ocupado;
  const pauta = editando ?? salva;
  const pautaAtual = pauta ?? pautaVazia;

  function mudarPauta(nova: PautaBoard) {
    if (!local.current) base.current = salva;
    setSituacao("");
    setEditando(nova);
  }

  function aceitarServidor() {
    setEditando(null);
    setConflito(false);
    setSituacao("");
  }

  async function desenvolver(ideia: IdeiaBoard) {
    if (!board) return;
    if (await enviar({acao: "desenvolver", ideia_id: ideia.id}, board.revisao)) {
      setRevisando(null);
      aceitarServidor();
      setManual(true);
    }
  }

  function escolher(ideia: IdeiaBoard) {
    if (pauta && pautaPreenchida(pauta)) setRevisando(ideia);
    else void desenvolver(ideia);
  }

  async function aplicarSugestao(mensagemId: string, campos: CampoPauta[]) {
    if (pendente && await salvar() !== "salvo") return;
    const atual = await carregar() ?? board;
    if (atual && await enviar({acao: "aplicar_sugestao", mensagem_id: mensagemId, campos}, atual.revisao)) {
      aceitarServidor();
      setManual(true);
    }
  }

  async function criarRoteiro(revisao: number, fluxo: string) {
    pedidoAprovacao.current = {revisao, fluxo};
    const runId = await aprovar(revisao, fluxo);
    if (!runId) return;
    // O rascunho novo não dispara sugestões agora: a pesquisa da execução criada usa o mesmo modelo.
    tentouInicial.current = true;
    pedidoAprovacao.current = null;
    aceitarServidor();
    setManual(false);
    router.push(`${baseUrl}/producao#/producao?run=${encodeURIComponent(runId)}`);
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
      <div><h1>Próximo vídeo</h1><p>Escolha um recorte e feche a pauta do canal.</p></div>
      <Link className="btn" href={baseUrl}>Vídeos e insights</Link>
    </header>
    <section className="panel board-context" aria-label="Histórico do canal">
      <h2>Histórico do canal</h2>
      <Atualizacao canal={canal} consulta="" estado={contexto.estado_analytics}
        estadoCatalogo={contexto.estado_catalogo} ultima={contexto.atualizado_em} atualizar={() => void carregar()}/>
      {contexto.observacoes.length > 0 && <details className="evidence-panel">
        <summary>Observações do período</summary>
        {contexto.observacoes.map(fonte => <FonteEditorial key={fonte.id} fonte={fonte}/>)}
      </details>}
    </section>

    {(falhaAcao || falhaLeitura) && <div className="insight-alert" role="alert">
      {falhaAcao?.mensagem || falhaLeitura}
      {falhaAcao?.conflito && <button type="button" className="btn" onClick={recarregarRevisao}>Carregar revisão atual</button>}
      {falhaAcao?.repetir && pedidoAprovacao.current && <button type="button" className="btn" disabled={ocupado}
        onClick={() => { const pedido = pedidoAprovacao.current; if (pedido) void criarRoteiro(pedido.revisao, pedido.fluxo); }}>
        Tentar de novo
      </button>}
    </div>}
    {board.ultima_aprovacao && <p className="insight-alert board-approved" role="status">
      Roteiro criado a partir da pauta “{board.ultima_aprovacao.titulo}” (revisão {board.ultima_aprovacao.revisao}).{" "}
      <Link href={`${baseUrl}/producao#/producao?run=${encodeURIComponent(board.ultima_aprovacao.run_id)}`}>Abrir execução</Link>
    </p>}
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
              {board.erro && board.operacao == null && !conversa.length ? "Tentar análise novamente" :
                board.propostas.length ? "Gerar novas propostas" : "Gerar propostas"}
            </button>}
          {selecionadas.length > 0 && <button className="btn" type="button"
            disabled={selecionadas.length !== 2 || ocupado || !!board.operacao}
            onClick={() => void enviar({tipo: "combinacao", ideias: selecionadas}, board.revisao)}>
            Combinar ideias ({selecionadas.length}/2)
          </button>}
        </div>
      </div>
      {board.operacao === "sugestoes" && <p role="status">Preparando sugestões…</p>}
      {board.operacao === "combinacao" && <p role="status">Combinando ideias…</p>}
      {board.erro && !conversa.length && <p role="status">A IA não concluiu a análise. Você pode continuar com a pauta manual.</p>}
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
    {conflito && editando && salva && <ConflitoPauta salva={salva} revisao={board.revisao} local={editando}
      ocupado={ocupado} descartar={aceitarServidor}
      reaplicar={() => { base.current = salva; setConflito(false); void salvar(); }}/>}

    <div className="board-workspace" data-aba={aba}>
      <div className="board-tabs" role="tablist" aria-label="Área de edição">
        {(["pauta", "conversa"] as const).map(item => <button key={item} type="button" role="tab"
          id={`board-tab-${item}`} aria-controls={`board-panel-${item}`} aria-selected={aba === item}
          className={aba === item ? "btn btn-primary" : "btn"} onClick={() => setAba(item)}>
          {item === "pauta" ? "Pauta" : "Conversa"}
        </button>)}
      </div>
      <section id="board-panel-pauta" role="tabpanel" aria-labelledby="board-tab-pauta"
        className="panel board-pauta board-pane-pauta">
        <div className="insight-section-header"><h2 id="board-pauta-title">Pauta</h2>
          {board.pauta && <small>Revisão {board.revisao}</small>}
        </div>
        {manual || pauta ? <EditorPauta pauta={pautaAtual} onChange={mudarPauta} ocupado={ocupado}
          situacao={conflito ? "Conflito com outra aba" : situacao || (pendente ? "Alterações não salvas" : "")}
          onSave={() => void salvar()}/> :
          <button className="btn" type="button" onClick={() => setManual(true)}>Abrir pauta manual</button>}
      </section>
      <section id="board-panel-conversa" role="tabpanel" aria-labelledby="board-tab-conversa"
        className="panel board-pane-conversa">
        <ConversaBoard conversa={conversa} pauta={salva ?? pautaVazia} ocupado={ocupado} editando={pendente}
          respondendo={board.operacao === "conversa"} falhou={!!board.erro}
          enviar={texto => enviar({tipo: "conversa", mensagem: texto}, board.revisao)}
          aplicar={(id, campos) => void aplicarSugestao(id, campos)}/>
      </section>
    </div>

    {(manual || pauta) && <DecisaoPauta board={board} pauta={salva ?? pautaVazia} pendenteLocal={pendente}
      ocupado={ocupado} escolherFluxo={fluxoId => void enviar({acao: "fluxo", fluxo_id: fluxoId}, board.revisao)}
      criar={board.fluxo_id ? () => void criarRoteiro(board.revisao, board.fluxo_id!) : undefined}/>}

    <EpisodiosBoard canal={canal} episodios={board.episodios ?? []}/>

    <section className="panel board-saved" aria-labelledby="board-saved-title">
      <h2 id="board-saved-title">Ideias guardadas</h2>
      {board.guardadas.length ? <ul>
        {board.guardadas.map(ideia => <li key={ideia.id}>
          <details className="evidence-panel"><summary>{ideia.pauta.titulo}</summary>
            <CorpoIdeia ideia={ideia}/>
          </details>
          <div className="board-actions">
            <button className="btn" type="button" disabled={!podeEditar} onClick={() => escolher(ideia)}>Desenvolver ideia guardada</button>
            <button className="btn" type="button" disabled={!podeEditar}
              onClick={() => void enviar({acao: "remover_guardada", ideia_id: ideia.id}, board.revisao)}>
              Remover <span className="sr-only">{ideia.pauta.titulo}</span>
            </button>
            {!candidatas.some(candidata => candidata.id === ideia.id) && controleSelecao(ideia)}
          </div>
        </li>)}
      </ul> : <p>Guarde uma proposta para retomá-la em outro episódio.</p>}
    </section>
  </main>;
}
