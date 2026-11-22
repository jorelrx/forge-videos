import { useEffect, useRef, type FormEvent } from "react";
import { camposPauta, type IdeiaBoard, type PautaBoard } from "../lib/board-criativo";

export function EditorPauta({pauta, onChange, onSave, ocupado}: {
  pauta: PautaBoard;
  onChange: (pauta: PautaBoard) => void;
  onSave: () => void;
  ocupado: boolean;
}) {
  function salvar(event: FormEvent) {
    event.preventDefault();
    onSave();
  }

  return <form className="board-form" onSubmit={salvar}>
    <div className="board-pauta-fields">
      {camposPauta.map(({chave, rotulo, limite}) => <label key={chave}>
        {rotulo}
        {limite <= 200 ? <input value={pauta[chave]} maxLength={limite}
          onChange={e => onChange({...pauta, [chave]: e.target.value})}/> :
          <textarea rows={2} value={pauta[chave]} maxLength={limite}
            onChange={e => onChange({...pauta, [chave]: e.target.value})}/>}
      </label>)}
    </div>
    <button className="btn btn-primary" disabled={ocupado || !Object.values(pauta).some(valor => valor.trim())} type="submit">Salvar pauta</button>
  </form>;
}

export function RevisarPauta({atual, ideia, aplicar, cancelar, ocupado}: {
  atual: PautaBoard;
  ideia: IdeiaBoard;
  aplicar: () => void;
  cancelar: () => void;
  ocupado: boolean;
}) {
  const mudancas = camposPauta.filter(({chave}) => atual[chave] !== ideia.pauta[chave]);
  const titulo = useRef<HTMLHeadingElement>(null);
  useEffect(() => { titulo.current?.focus(); }, [ideia.id]);
  return <section className="panel board-review" aria-labelledby="board-review-title">
    <h2 ref={titulo} tabIndex={-1} id="board-review-title">Revisar mudanças na pauta</h2>
    {mudancas.length ? <dl>
      {mudancas.map(({chave, rotulo}) => <div key={chave}>
        <dt>{rotulo}</dt>
        <dd><span>Atual</span>{atual[chave] || "Vazio"}</dd>
        <dd><span>Proposta</span>{ideia.pauta[chave] || "Vazio"}</dd>
      </div>)}
    </dl> : <p>Os campos da proposta já coincidem com a pauta.</p>}
    <div className="board-actions">
      <button className="btn btn-primary" type="button" disabled={ocupado} onClick={aplicar}>Aplicar proposta à pauta</button>
      <button className="btn" type="button" onClick={cancelar}>Cancelar</button>
    </div>
  </section>;
}
