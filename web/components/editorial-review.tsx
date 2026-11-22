"use client";

import { useState } from "react";
import { artifactContentUrl } from "../lib/api";
import type { DecisaoAbertura, EscolhaEditorial, JsonValue, RunView } from "../lib/contracts";

const campos = [
  ["situacao", "Cena de abertura"],
  ["pergunta", "Pergunta do vídeo"],
  ["virada", "Virada filosófica"],
  ["fecho", "Retorno no fecho"],
  ["thumbnail", "Ideia de thumbnail"],
  ["fonte", "Passagem no acervo"],
] as const;

function eObjeto(value: JsonValue | undefined): value is { readonly [key: string]: JsonValue } {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function objetos(value: JsonValue | undefined) {
  return Array.isArray(value) ? value.filter(eObjeto) : [];
}

export function EditorialReview({
  run, escolher, decidir,
}: {
  run: RunView;
  escolher?: (input: EscolhaEditorial) => Promise<void>;
  decidir?: (input: DecisaoAbertura) => Promise<void>;
}) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [tituloIndex, setTituloIndex] = useState(0);
  const config = run.run.config_snapshot ?? {};
  const checkpoint = config.aguardando_editorial;
  const proposta = config.proposta_editorial;
  const previa = run.artifacts?.find((item) => item.kind === "previa_abertura");
  const propostas = run.artifacts?.find((item) => item.kind === "propostas_editoriais");
  const thumbnail = run.artifacts?.find((item) => item.kind === "abertura.thumbnail");
  const editavel = run.run.status === "paused" && checkpoint === "previa_abertura" && !!decidir;
  const titulos = Array.isArray(previa?.metadata.titulos) ? previa.metadata.titulos.map(String) : [];

  async function executar(acao: () => Promise<void>) {
    setErro("");
    setOcupado(true);
    try {
      await acao();
    } catch (error) {
      setErro(error instanceof Error ? error.message : "Não foi possível registrar a escolha.");
    } finally {
      setOcupado(false);
    }
  }

  if (!config.revisao_editorial) return null;

  return (
    <section className="panel editorial-panel" aria-label="Revisão editorial">
      {erro && <p role="alert" className="editorial-error">{erro}</p>}
      {checkpoint === "propostas_editoriais" && propostas && (
        <>
          <h3>Escolha o recorte do vídeo</h3>
          <div className="editorial-options">
            {objetos(propostas.metadata.propostas).map((item, indice) => (
              <article key={indice} className="editorial-proposal">
                <h4>{String(item.titulo)}</h4>
                <dl>
                  {campos.map(([chave, label]) => (
                    <div key={chave}><dt>{label}</dt><dd>{String(item[chave] ?? "")}</dd></div>
                  ))}
                </dl>
                <button
                  type="button" className="btn btn-primary" disabled={ocupado || !escolher}
                  onClick={() => escolher && void executar(() => escolher({ artefato_id: propostas.id, indice }))}
                >
                  Usar este recorte
                </button>
              </article>
            ))}
          </div>
        </>
      )}
      {eObjeto(proposta) && (
        <div className="editorial-selected"><h3>Recorte escolhido</h3><p>{String(proposta.titulo)}</p></div>
      )}
      {previa && (
        <>
          <h3>Prévia da abertura</h3>
          <div className="editorial-preview">
            <video key={previa.id} controls preload="metadata" aria-label="Prévia dos primeiros segundos"
              src={artifactContentUrl(previa.id)} />
            <div className="editorial-packaging">
              {thumbnail && (
                // Os artefatos são servidos pelo Studio local.

                <img src={artifactContentUrl(thumbnail.id)} alt="Thumbnail proposta" />
              )}
              {!thumbnail && <p className="field-hint">Thumbnail indisponível nesta prévia.</p>}
              <p className="editorial-preview-title">{titulos[tituloIndex] ?? titulos[0]}</p>
              {titulos.length > 1 && <label className="field">
                Título na prévia
                <select value={titulos[tituloIndex] ? tituloIndex : 0}
                  onChange={(event) => setTituloIndex(Number(event.target.value))}>
                  {titulos.map((titulo, index) => <option key={titulo} value={index}>{titulo}</option>)}
                </select>
              </label>}
            </div>
          </div>
          {editavel && decidir && (
            <>
              <details className="editorial-adjustments">
                <summary>Ajustar narração ou imagens</summary>
                {objetos(previa.metadata.itens_audio).map((item) => (
                  <div key={String(item.id)} className="editorial-adjustment">
                    <p>{String(item.texto)}</p>
                    <button type="button" className="btn btn-sm" disabled={ocupado}
                      onClick={() => void executar(() => decidir({
                        artefato_id: previa.id, acao: "audio", item: String(item.id),
                      }))}>Gerar outra leitura</button>
                  </div>
                ))}
                {objetos(previa.metadata.itens_imagem).map((item, index) => {
                  const imagem = run.artifacts.find((a) => a.kind === "abertura.imagem" && a.metadata.item === item.id);
                  const inputId = "editorial-cena-" + String(item.id);
                  return (
                    <form key={String(item.id)} className="editorial-adjustment" onSubmit={(event) => {
                      event.preventDefault();
                      const orientacao = String(new FormData(event.currentTarget).get("orientacao") ?? "").trim();
                      void executar(() => decidir({
                        artefato_id: previa.id, acao: "imagem", item: String(item.id),
                        ...(orientacao ? { orientacao } : {}),
                      }));
                    }}>
                      {imagem && (

                        <img src={artifactContentUrl(imagem.id)} alt={"Cena " + (index + 1)} />
                      )}
                      <div className="field">
                        <label htmlFor={inputId}>Direção da cena {index + 1}</label>
                        <textarea id={inputId} name="orientacao" rows={2} maxLength={1000} placeholder="Ajuste opcional" />
                      </div>
                      <button className="btn btn-sm" type="submit" disabled={ocupado}>Gerar outra imagem</button>
                    </form>
                  );
                })}
              </details>
              <button type="button" className="btn btn-primary" disabled={ocupado}
                onClick={() => void executar(() => decidir({ artefato_id: previa.id, acao: "aprovar" }))}>
                Aprovar abertura e gerar vídeo
              </button>
            </>
          )}
        </>
      )}
      {!checkpoint && !proposta && <p>Os recortes aparecem depois da pesquisa no acervo.</p>}
      {proposta && !previa && <p>A prévia aparece após o roteiro e o plano de mídia.</p>}
    </section>
  );
}
