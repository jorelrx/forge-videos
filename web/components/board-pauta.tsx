import { useEffect, useRef, type FormEvent } from "react";
import {
  camposPauta, completarPauta, mesmoValor, pautaPreenchida, type DefinicaoCampo, type PautaBoard, type PautaInicial,
  type ValorCampo,
} from "../lib/board-criativo";

export function exibirValor(valor: ValorCampo | undefined) {
  if (Array.isArray(valor)) return valor.length ? valor.map((item, i) => `${i + 1}. ${item}`).join("\n") : "Vazio";
  return valor || "Vazio";
}

function CampoLista({campo, valor, mudar}: {campo: DefinicaoCampo; valor: string[]; mudar: (itens: string[]) => void}) {
  if (campo.lista === "linhas") {
    return <label>{campo.rotulo} <small>uma por linha</small>
      <textarea rows={3} value={valor.join("\n")} onChange={e => mudar(e.target.value.split("\n"))}/>
    </label>;
  }
  const mover = (de: number, para: number) => {
    const itens = [...valor];
    [itens[de], itens[para]] = [itens[para], itens[de]];
    mudar(itens);
  };
  return <fieldset className="board-blocos">
    <legend>{campo.rotulo}</legend>
    {valor.length === 0 && <p>Nenhum bloco ainda.</p>}
    <ol>
      {valor.map((item, i) => <li key={i}>
        <label><span className="sr-only">Bloco {i + 1}</span>
          <textarea rows={2} value={item} maxLength={campo.limite}
            onChange={e => mudar(valor.map((atual, j) => j === i ? e.target.value : atual))}/>
        </label>
        <div className="board-actions">
          <button type="button" className="btn" disabled={i === 0} onClick={() => mover(i, i - 1)}
            aria-label={`Subir bloco ${i + 1}`}>↑</button>
          <button type="button" className="btn" disabled={i === valor.length - 1} onClick={() => mover(i, i + 1)}
            aria-label={`Descer bloco ${i + 1}`}>↓</button>
          <button type="button" className="btn" onClick={() => mudar(valor.filter((_, j) => j !== i))}
            aria-label={`Remover bloco ${i + 1}`}>Remover</button>
        </div>
      </li>)}
    </ol>
    <button type="button" className="btn" disabled={valor.length >= 12} onClick={() => mudar([...valor, ""])}>
      Adicionar bloco
    </button>
  </fieldset>;
}

export function EditorPauta({pauta, onChange, onSave, ocupado, situacao}: {
  pauta: PautaBoard;
  onChange: (pauta: PautaBoard) => void;
  onSave: () => void;
  ocupado: boolean;
  situacao?: string;
}) {
  function salvar(event: FormEvent) {
    event.preventDefault();
    onSave();
  }

  return <form className="board-form" onSubmit={salvar}>
    <div className="board-pauta-fields">
      {camposPauta.map(campo => {
        const valor = pauta[campo.chave];
        if (campo.lista) {
          return <CampoLista key={campo.chave} campo={campo} valor={valor as string[]}
            mudar={itens => onChange({...pauta, [campo.chave]: itens})}/>;
        }
        return <label key={campo.chave}>
          {campo.rotulo}
          {campo.limite <= 200 ? <input value={valor as string} maxLength={campo.limite}
            onChange={e => onChange({...pauta, [campo.chave]: e.target.value})}/> :
            <textarea rows={2} value={valor as string} maxLength={campo.limite}
              onChange={e => onChange({...pauta, [campo.chave]: e.target.value})}/>}
        </label>;
      })}
    </div>
    <div className="board-actions">
      <button className="btn btn-primary" disabled={ocupado || !pautaPreenchida(pauta)} type="submit">Salvar pauta</button>
      {situacao && <small role="status">{situacao}</small>}
    </div>
  </form>;
}

export function RevisarPauta({atual, ideia, aplicar, cancelar, ocupado}: {
  atual: PautaBoard;
  ideia: {id: string; pauta: PautaInicial};
  aplicar: () => void;
  cancelar: () => void;
  ocupado: boolean;
}) {
  const proposta = completarPauta(ideia.pauta);
  const mudancas = camposPauta.filter(({chave}) => !mesmoValor(atual[chave], proposta[chave]));
  const titulo = useRef<HTMLHeadingElement>(null);
  useEffect(() => { titulo.current?.focus(); }, [ideia.id]);
  return <section className="panel board-review" aria-labelledby="board-review-title">
    <h2 ref={titulo} tabIndex={-1} id="board-review-title">Revisar mudanças na pauta</h2>
    {mudancas.length ? <dl>
      {mudancas.map(({chave, rotulo}) => <div key={chave}>
        <dt>{rotulo}</dt>
        <dd><span>Atual</span>{exibirValor(atual[chave])}</dd>
        <dd><span>Proposta</span>{exibirValor(proposta[chave])}</dd>
      </div>)}
    </dl> : <p>Os campos da proposta já coincidem com a pauta.</p>}
    <div className="board-actions">
      <button className="btn btn-primary" type="button" disabled={ocupado} onClick={aplicar}>Aplicar proposta à pauta</button>
      <button className="btn" type="button" onClick={cancelar}>Cancelar</button>
    </div>
  </section>;
}

export function ConflitoPauta({salva, revisao, local, reaplicar, descartar, ocupado}: {
  salva: PautaBoard;
  revisao: number;
  local: PautaBoard;
  reaplicar: () => void;
  descartar: () => void;
  ocupado: boolean;
}) {
  const diferentes = camposPauta.filter(({chave}) => !mesmoValor(salva[chave], local[chave]));
  return <section className="panel board-review" role="alert" aria-labelledby="board-conflict-title">
    <h2 id="board-conflict-title">Outra aba salvou a pauta (revisão {revisao})</h2>
    <p>Compare a versão salva com a sua edição. Reaplicar grava a sua edição sobre a revisão {revisao}.</p>
    <dl>
      {diferentes.map(({chave, rotulo}) => <div key={chave}>
        <dt>{rotulo}</dt>
        <dd><span>Versão salva</span>{exibirValor(salva[chave])}</dd>
        <dd><span>Sua edição</span>{exibirValor(local[chave])}</dd>
      </div>)}
    </dl>
    <div className="board-actions">
      <button className="btn btn-primary" type="button" disabled={ocupado} onClick={reaplicar}>Reaplicar minha edição</button>
      <button className="btn" type="button" disabled={ocupado} onClick={descartar}>Manter a versão salva</button>
    </div>
  </section>;
}
