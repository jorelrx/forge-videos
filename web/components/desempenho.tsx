"use client";

import { useEffect, useState } from "react";
import { getPerformance, savePerformance } from "../lib/api";
import type { Desempenho } from "../lib/contracts";

const campos = [
  { id: "visualizacoes", label: "Visualizações" },
  { id: "impressoes", label: "Impressões" },
  { id: "ctr", label: "CTR (%)", percentual: true },
  { id: "retencao_30s", label: "Permanência aos 30 s (%)", percentual: true },
  { id: "percentual_assistido", label: "Média assistida (%)", decimal: true },
  { id: "comentarios", label: "Comentários" },
  { id: "respostas_lidas", label: "Comentários da amostra" },
  { id: "respostas_substantivas", label: "Com relato, escolha ou objeção" },
  { id: "cliques_tela_final", label: "Cliques na tela final" },
] as const;

export function DesempenhoPublicacao({ runId }: { runId: string }) {
  const [janela, setJanela] = useState<7 | 28>(7);
  const [dados, setDados] = useState<Desempenho | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [salvo, setSalvo] = useState(false);
  const [aberto, setAberto] = useState(false);
  const medicao = dados?.medicoes.find((item) => item.janela === janela);

  useEffect(() => {
    if (!aberto) return;
    let ativo = true;
    getPerformance(runId).then(
      (value) => {
        if (!ativo) return;
        if (!value || !Array.isArray(value.medicoes)) {
          setErro("O Studio não retornou as medições do vídeo.");
          return;
        }
        setDados(value);
        setErro("");
      },
      (error: Error) => { if (ativo) setErro(error.message); },
    );
    return () => { ativo = false; };
  }, [runId, aberto]);

  return (
    <details className="editorial-performance" onToggle={(event) => setAberto(event.currentTarget.open)}>
      <summary>Desempenho no YouTube</summary>
      <p className="pub-muted">Registre os totais dos primeiros 7 ou 28 dias após o vídeo se tornar público.</p>
      {dados?.fluxo_geracao && <p className="pub-muted">Fluxo publicado: {dados.fluxo_geracao}</p>}
      {erro && <p className="editorial-error" role="alert">{erro}</p>}
      <label className="field">
        Janela de medição
        <select value={janela} disabled={ocupado} onChange={(event) => {
          setJanela(event.target.value === "28" ? 28 : 7);
          setSalvo(false);
        }}>
          <option value={7}>D+7</option>
          <option value={28}>D+28</option>
        </select>
      </label>
      <form key={janela + "-" + !!medicao} className="editorial-measure-form" onSubmit={async (event) => {
        event.preventDefault();
        const dadosForm = new FormData(event.currentTarget);
        const numero = (key: string) => {
          const valor = dadosForm.get(key);
          return valor === "" || valor == null ? null : Number(valor);
        };
        setErro("");
        setSalvo(false);
        setOcupado(true);
        try {
          const atualizados = await savePerformance(runId, {
            janela,
            visualizacoes: numero("visualizacoes") ?? 0,
            impressoes: numero("impressoes"),
            ctr: numero("ctr"),
            origem_trafego: String(dadosForm.get("origem_trafego") ?? "").trim(),
            retencao_30s: numero("retencao_30s"),
            percentual_assistido: numero("percentual_assistido"),
            comentarios: numero("comentarios"),
            respostas_lidas: numero("respostas_lidas"),
            respostas_substantivas: numero("respostas_substantivas"),
            cliques_tela_final: numero("cliques_tela_final"),
          });
          if (!atualizados || !Array.isArray(atualizados.medicoes)) {
            throw new Error("O Studio não confirmou a medição.");
          }
          setDados(atualizados);
          setSalvo(true);
        } catch (error) {
          setErro(error instanceof Error ? error.message : "Não foi possível salvar os resultados.");
        } finally {
          setOcupado(false);
        }
      }}>
        <fieldset disabled={ocupado || !dados}>
          {campos.map((campo) => {
            const percentual = "percentual" in campo;
            const decimal = percentual || "decimal" in campo;
            return <label className="field" key={campo.id}>
              {campo.label}
              <input name={campo.id} type="number" min={0} max={percentual ? 100 : undefined}
                step={decimal ? "any" : 1} defaultValue={medicao?.[campo.id] ?? ""}
                required={campo.id === "visualizacoes"} />
            </label>;
          })}
          <label className="field">
            Origem do CTR
            <input name="origem_trafego" maxLength={80} defaultValue={medicao?.origem_trafego ?? ""} />
          </label>
        </fieldset>
        <button type="submit" className="btn btn-sm" disabled={ocupado || !dados}>Salvar medição</button>
        {salvo && <span role="status">Medição salva.</span>}
        {medicao?.comentarios_por_mil != null && (
          <p className="pub-muted">{medicao.comentarios_por_mil.toLocaleString("pt-BR")} comentários por mil views</p>
        )}
      </form>
    </details>
  );
}
