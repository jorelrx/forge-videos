import type { Board, PautaBoard } from "../lib/board-criativo";

export function DecisaoPauta({board, pauta, pendenteLocal, ocupado, escolherFluxo, criar}: {
  board: Board;
  pauta: PautaBoard;
  pendenteLocal: boolean;
  ocupado: boolean;
  escolherFluxo: (fluxoId: string) => void;
  criar?: () => void;
}) {
  const fluxo = board.fluxos.find(item => item.id === board.fluxo_id);
  const motivo = pendenteLocal ? "Salve as alterações da pauta antes de criar o roteiro." :
    board.pendencias[0]?.mensagem ?? (board.operacao ? "Aguarde a IA terminar." : "");
  return <section className="panel board-decision" aria-labelledby="board-decision-title">
    <h2 id="board-decision-title">Revisão final</h2>
    <dl className="board-angle">
      <div><dt>Tema</dt><dd>{pauta.tema || "Pendente"}</dd></div>
      <div><dt>Promessa</dt><dd>{pauta.promessa || "Pendente"}</dd></div>
      <div><dt>Blocos</dt><dd>{pauta.blocos.length ? <ol>{pauta.blocos.map((b, i) => <li key={i}>{b}</li>)}</ol> : "Pendente"}</dd></div>
      <div><dt>Perguntas de pesquisa</dt><dd>{pauta.perguntas_pesquisa.length
        ? <ul>{pauta.perguntas_pesquisa.map((p, i) => <li key={i}>{p}</li>)}</ul> : "Nenhuma"}</dd></div>
    </dl>
    <label className="board-flow">Fluxo de geração
      <select value={board.fluxo_id ?? ""} disabled={ocupado} onChange={e => e.target.value && escolherFluxo(e.target.value)}>
        <option value="">Escolha um fluxo</option>
        {board.fluxos.map(item => <option key={item.id} value={item.id} disabled={!item.disponivel}>
          {item.nome}{item.disponivel ? "" : ` — ${item.motivo ?? "indisponível"}`}
        </option>)}
      </select>
    </label>
    {fluxo && <p className="board-flow-description">{fluxo.descricao}</p>}
    {board.pendencias.length > 0 && <ul className="board-pending" aria-label="Pendências">
      {board.pendencias.map(item => <li key={item.campo}>{item.mensagem}</li>)}
    </ul>}
    <div className="board-actions">
      <button type="button" className="btn btn-primary" disabled={!criar || !!motivo || ocupado}
        aria-describedby="board-create-reason" onClick={criar}>Criar roteiro</button>
      {motivo && <small id="board-create-reason">{motivo}</small>}
    </div>
  </section>;
}
