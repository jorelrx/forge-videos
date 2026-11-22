import { useState, type FormEvent } from "react";
import {
  mesmoValor, rotuloCampo, type CampoPauta, type MensagemBoard, type PautaBoard,
} from "../lib/board-criativo";
import { exibirValor } from "./board-pauta";

function Sugestao({mensagem, pauta, ocupado, aplicar}: {
  mensagem: MensagemBoard;
  pauta: PautaBoard;
  ocupado: boolean;
  aplicar: (campos: CampoPauta[]) => void;
}) {
  const [marcados, setMarcados] = useState<CampoPauta[]>([]);
  const pendentes = mensagem.alteracoes.filter(a => !mensagem.aplicadas.includes(a.campo));
  if (!mensagem.alteracoes.length) return null;
  return <div className="board-suggestion">
    <p className="board-suggestion-base">Sugestão sobre a revisão {mensagem.base_revisao}</p>
    {mensagem.alteracoes.map(alteracao => {
      const aplicada = mensagem.aplicadas.includes(alteracao.campo);
      const mudou = !mesmoValor(pauta[alteracao.campo], alteracao.anterior);
      return <div key={alteracao.campo} className="board-suggestion-field">
        <label className="board-check">
          <input type="checkbox" disabled={aplicada || ocupado} checked={aplicada || marcados.includes(alteracao.campo)}
            onChange={() => setMarcados(marcados.includes(alteracao.campo)
              ? marcados.filter(c => c !== alteracao.campo) : [...marcados, alteracao.campo])}/>
          {rotuloCampo(alteracao.campo)}{aplicada && <small> · aplicada</small>}
        </label>
        <dl>
          <div><dt>Antes</dt><dd>{exibirValor(alteracao.anterior)}</dd></div>
          {mudou && !aplicada && <div><dt>Agora na pauta</dt><dd>{exibirValor(pauta[alteracao.campo])}</dd></div>}
          <div><dt>Proposta</dt><dd>{exibirValor(alteracao.valor)}</dd></div>
        </dl>
      </div>;
    })}
    {pendentes.length > 0 && <button type="button" className="btn btn-primary"
      disabled={ocupado || !marcados.length} onClick={() => { aplicar(marcados); setMarcados([]); }}>
      Aplicar selecionadas ({marcados.length})
    </button>}
  </div>;
}

export function ConversaBoard({conversa, pauta, respondendo, outraAnalise, falhou, ocupado, editando, enviar, aplicar}: {
  conversa: MensagemBoard[];
  pauta: PautaBoard;
  respondendo: boolean;
  outraAnalise: boolean;
  falhou: boolean;
  ocupado: boolean;
  editando: boolean;
  enviar: (texto: string) => Promise<boolean>;
  aplicar: (mensagemId: string, campos: CampoPauta[]) => void;
}) {
  const [texto, setTexto] = useState("");
  const ultima = conversa[conversa.length - 1];

  async function submeter(event: FormEvent) {
    event.preventDefault();
    if (texto.trim() && await enviar(texto.trim())) setTexto("");
  }

  return <div className="board-chat">
    <h2 id="board-chat-title">Conversa</h2>
    {conversa.length === 0 && <p>Peça à IA um ajuste em um campo da pauta, por exemplo outra abertura.</p>}
    <ol className="board-chat-log">
      {conversa.map(mensagem => <li key={mensagem.id} data-autor={mensagem.autor}>
        <strong>{mensagem.autor === "ia" ? "IA" : "Você"}</strong>
        <p>{mensagem.texto}</p>
        {mensagem.autor === "ia" && <Sugestao mensagem={mensagem} pauta={pauta} ocupado={ocupado}
          aplicar={campos => aplicar(mensagem.id, campos)}/>}
      </li>)}
    </ol>
    {respondendo && <p role="status">A IA está respondendo…</p>}
    {falhou && ultima?.autor === "criador" && !respondendo &&
      <p role="status">A IA não respondeu. Sua mensagem ficou salva; envie de novo para tentar outra vez.</p>}
    <form className="board-form" onSubmit={submeter}>
      <label>Mensagem
        <textarea rows={3} maxLength={2000} value={texto} onChange={e => setTexto(e.target.value)}/>
      </label>
      {editando && <small>A IA considera a última revisão salva da pauta.</small>}
      {outraAnalise && <small>Aguarde a análise de propostas terminar para enviar.</small>}
      <button type="submit" className="btn" disabled={ocupado || respondendo || outraAnalise || !texto.trim()}>Enviar</button>
    </form>
  </div>;
}
