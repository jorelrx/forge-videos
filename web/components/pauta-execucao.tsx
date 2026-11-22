"use client";

import { useState, type FormEvent } from "react";
import type { DecisaoConflitoPauta, JsonValue, RunView } from "../lib/contracts";

type Objeto = { readonly [key: string]: JsonValue };

function objeto(valor: JsonValue | undefined): Objeto | null {
  return valor != null && typeof valor === "object" && !Array.isArray(valor) ? valor as Objeto : null;
}

const texto = (valor: JsonValue | undefined) => typeof valor === "string" ? valor : "";

function Recorte({titulo, pauta}: {titulo: string; pauta: Objeto}) {
  return <div className="pauta-run-versao">
    <h3>{titulo}</h3>
    <dl className="board-angle">
      <div><dt>Promessa</dt><dd>{texto(pauta.promessa) || "Sem promessa"}</dd></div>
      <div><dt>Recorte</dt><dd>{texto(pauta.recorte) || "Sem recorte"}</dd></div>
    </dl>
  </div>;
}

export function PautaExecucao({run, decidir}: {
  run: RunView;
  decidir?: (input: DecisaoConflitoPauta) => Promise<void>;
}) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [editando, setEditando] = useState(false);
  const config = run.run.config_snapshot ?? {};
  const aprovada = objeto(config.pauta_aprovada);
  const decidida = objeto(config.pauta_decidida);
  const decisao = objeto(config.decisao_pauta);
  const conflito = run.artifacts?.find(item => item.kind === "conflito_pauta" && item.is_current !== false);
  const aguardando = run.run.status === "paused" && config.aguardando_editorial === "conflito_pauta" && !!conflito;
  if (!aprovada) return null;
  const meta = (conflito?.metadata ?? {}) as Objeto;
  const evidencias = Array.isArray(meta.evidencias) ? meta.evidencias.map(objeto).filter(Boolean) as Objeto[] : [];

  async function enviar(input: Omit<DecisaoConflitoPauta, "artefato_id">) {
    if (!decidir || !conflito) return;
    setErro("");
    setOcupado(true);
    try {
      await decidir({artefato_id: conflito.id, ...input});
      setEditando(false);
    } catch (error) {
      setErro(error instanceof Error ? error.message : "Não foi possível registrar a decisão.");
    } finally {
      setOcupado(false);
    }
  }

  function enviarEdicao(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const dados = new FormData(event.currentTarget);
    const promessa = String(dados.get("promessa") ?? "").trim();
    const recorte = String(dados.get("recorte") ?? "").trim();
    void enviar({acao: "editar", ...(promessa ? {promessa} : {}), ...(recorte ? {recorte} : {})});
  }

  return <section className="panel editorial-panel pauta-run" aria-label="Pauta do Board">
    <h2>Pauta do Board</h2>
    <p>Aprovada na revisão {String(aprovada.revisao ?? "")}{texto(aprovada.titulo) ? ` · ${texto(aprovada.titulo)}` : ""}</p>
    <Recorte titulo="Pauta aprovada" pauta={aprovada}/>
    {decisao && <p className="pauta-run-decisao">
      Decisão após a pesquisa: {decisao.acao === "aceitar" ? "recorte proposto aceito" :
        decisao.acao === "editar" ? "pauta editada à luz das fontes" : "encaminhamento cancelado"}
    </p>}
    {decidida && <Recorte titulo="Recorte recebido pela escrita" pauta={decidida}/>}
    {!decidida && !aguardando && decisao?.acao !== "cancelar" && <p>A escrita recebe a pauta aprovada.</p>}
    {erro && <p role="alert" className="editorial-error">{erro}</p>}
    {aguardando && <div className="pauta-run-conflito" role="group" aria-label="Conflito com o acervo">
      <h3>A pesquisa contraria a pauta</h3>
      <p>{texto(meta.explicacao)}</p>
      {evidencias.map(item => <blockquote key={texto(item.path)}>
        <p>{texto(item.trecho)}</p><cite>{texto(item.titulo)} · {texto(item.path)}</cite>
      </blockquote>)}
      <dl className="board-angle">
        <div><dt>Promessa proposta</dt><dd>{texto(meta.promessa_proposta)}</dd></div>
        <div><dt>Recorte proposto</dt><dd>{texto(meta.recorte_proposto)}</dd></div>
      </dl>
      {editando ? <form className="board-form" onSubmit={enviarEdicao}>
        <label>Promessa<textarea name="promessa" rows={2} maxLength={1200} defaultValue={texto(meta.promessa_proposta)}/></label>
        <label>Recorte<textarea name="recorte" rows={2} maxLength={1200} defaultValue={texto(meta.recorte_proposto)}/></label>
        <div className="board-actions">
          <button type="submit" className="btn btn-primary" disabled={ocupado}>Salvar e continuar</button>
          <button type="button" className="btn" onClick={() => setEditando(false)}>Voltar</button>
        </div>
      </form> : <div className="board-actions">
        <button type="button" className="btn btn-primary" disabled={ocupado || !decidir}
          onClick={() => void enviar({acao: "aceitar"})}>Aceitar recorte proposto</button>
        <button type="button" className="btn" disabled={ocupado || !decidir} onClick={() => setEditando(true)}>Editar promessa ou recorte</button>
        <button type="button" className="btn" disabled={ocupado || !decidir}
          onClick={() => void enviar({acao: "cancelar"})}>Cancelar encaminhamento</button>
      </div>}
    </div>}
  </section>;
}
