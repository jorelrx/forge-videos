"use client";
import React, { forwardRef, useEffect, useRef, useState } from "react";
import type { StudioApi } from "../lib/api";
import type { CreateVideoRequest, FluxoGeracao } from "../lib/contracts";

export interface NewVideoFormProps {
  onSubmit: (input: CreateVideoRequest) => void | Promise<void>;
  disabled?: boolean;
  fluxosApi?: Pick<StudioApi, "getGenerationFlows" | "createGenerationFlow">;
}

const FLUXO_PADRAO = "padrao";

export const NewVideoForm = forwardRef<HTMLFormElement, NewVideoFormProps>(
  function NewVideoForm({ onSubmit, disabled, fluxosApi }, ref) {
    const [tema, setTema] = useState("");
    const [tese, setTese] = useState("");
    const [priority, setPriority] = useState(50);
    const [fluxos, setFluxos] = useState<FluxoGeracao[]>([]);
    const [fluxoId, setFluxoId] = useState(FLUXO_PADRAO);
    const [erroCatalogo, setErroCatalogo] = useState(false);
    const [tentativaCatalogo, setTentativaCatalogo] = useState(0);
    const [salvando, setSalvando] = useState(false);
    const [erroCadastro, setErroCadastro] = useState("");
    const cadastroRef = useRef<HTMLDetailsElement>(null);
    const seletorRef = useRef<HTMLSelectElement>(null);
    const fluxo = fluxos.find((item) => item.id === fluxoId);

    useEffect(() => {
      if (!fluxosApi) return;
      let ativo = true;
      void fluxosApi.getGenerationFlows().then(
        (items) => { if (ativo) setFluxos(items); },
        () => { if (ativo) setErroCatalogo(true); },
      );
      return () => { ativo = false; };
    }, [fluxosApi, tentativaCatalogo]);

    async function criarFluxo(event: React.FormEvent<HTMLFormElement>) {
      event.preventDefault();
      if (!fluxosApi || salvando) return;
      const form = event.currentTarget;
      const dados = new FormData(form);
      setSalvando(true);
      setErroCadastro("");
      try {
        const novo = await fluxosApi.createGenerationFlow({
          nome: String(dados.get("nome")).trim(),
          descricao: String(dados.get("descricao")).trim(),
          instrucoes: String(dados.get("instrucoes")).trim(),
        });
        setFluxos((atuais) => [...atuais, novo]);
        setFluxoId(novo.id);
        form.reset();
        if (cadastroRef.current) cadastroRef.current.open = false;
        seletorRef.current?.focus();
      } catch (error) {
        setErroCadastro(error instanceof Error ? error.message : "Não foi possível criar o fluxo.");
      } finally {
        setSalvando(false);
      }
    }

    function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
      event.preventDefault();
      const normalizedTema = tema.trim();
      if (!normalizedTema) return;
      const normalizedTese = tese.trim();
      onSubmit({
        tema: normalizedTema,
        tese: normalizedTese || null,
        priority,
        preset: "local-recomendado-v1",
        fluxo_geracao: fluxoId,
      });
    }

    return (
      <>
        <form
          ref={ref}
          className="video-form"
          data-testid="new-video-form"
          onSubmit={handleSubmit}
        >
          <fieldset disabled={disabled}>
            <div className="field">
              <label htmlFor="tema">Tema</label>
              <input
                id="tema"
                name="tema"
                type="text"
                autoComplete="off"
                placeholder="Ex.: Por que adiamos o que importa"
                value={tema}
                onChange={(event) => setTema(event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="tese">
                Tese opcional
              </label>
              <textarea
                id="tese"
                name="tese"
                rows={3}
                aria-describedby="tese-hint"
                value={tese}
                onChange={(event) => setTese(event.target.value)}
              />
              <small id="tese-hint" className="field-hint">
                Em branco, o planejamento escolhe a tese que o acervo sustenta.
              </small>
            </div>
            <div className="field">
              <label htmlFor="fluxo-geracao">Fluxo de geração</label>
              <select
                ref={seletorRef}
                id="fluxo-geracao"
                name="fluxo_geracao"
                aria-describedby="fluxo-geracao-hint"
                value={fluxoId}
                onChange={(event) => setFluxoId(event.target.value)}
              >
                {fluxos.length === 0 && <option value={FLUXO_PADRAO}>Padrão</option>}
                {fluxos.map((item) => <option key={item.id} value={item.id}>{item.nome}</option>)}
              </select>
              <small id="fluxo-geracao-hint" className="field-hint">
                {fluxo?.descricao ?? (
                  erroCatalogo ? "A lista de fluxos está indisponível." :
                    fluxosApi ? "Carregando fluxos…" : "Roteiro com tese e evidências do acervo."
                )}
              </small>
              {erroCatalogo && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setErroCatalogo(false);
                    setTentativaCatalogo((tentativa) => tentativa + 1);
                  }}
                >
                  Recarregar fluxos
                </button>
              )}
            </div>
            <div className="form-row">
              <div className="field field-priority">
                <label htmlFor="priority">Prioridade</label>
                <input
                  id="priority"
                  name="priority"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  max="100"
                  value={priority}
                  onChange={(event) => setPriority(Number(event.target.value))}
                />
              </div>
              <button className="btn btn-primary btn-block" type="submit">
                Enfileirar vídeo
              </button>
            </div>
          </fieldset>
        </form>
        {fluxosApi && fluxos.length > 0 && (
          <details className="video-flow-create" ref={cadastroRef}>
            <summary>Criar fluxo</summary>
            <form className="video-form" onSubmit={criarFluxo}>
              <fieldset disabled={disabled || salvando}>
                <div className="field">
                  <label htmlFor="novo-fluxo-nome">Nome do fluxo</label>
                  <input id="novo-fluxo-nome" name="nome" maxLength={80} required />
                </div>
                <div className="field">
                  <label htmlFor="novo-fluxo-descricao">Descrição</label>
                  <input id="novo-fluxo-descricao" name="descricao" maxLength={240} required />
                </div>
                <div className="field">
                  <label htmlFor="novo-fluxo-instrucoes">Instruções para o roteiro</label>
                  <textarea
                    id="novo-fluxo-instrucoes"
                    name="instrucoes"
                    rows={4}
                    maxLength={4000}
                    placeholder="Ex.: apresente duas escolhas no início e, no Fecho, peça ao público que justifique sua decisão."
                    required
                  />
                </div>
                {erroCadastro && <small className="flow-form-error" role="alert">{erroCadastro}</small>}
                <button className="btn btn-sm" type="submit">
                  {salvando ? "Salvando…" : "Salvar fluxo"}
                </button>
              </fieldset>
            </form>
          </details>
        )}
      </>
    );
  },
);
