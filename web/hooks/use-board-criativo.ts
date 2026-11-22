"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, studioRequest } from "../lib/api";
import { mesmaPauta, type Board, type ComandoBoard, type PautaBoard, type PedidoBoard } from "../lib/board-criativo";

export type ResultadoPauta = {estado: "salvo"; board: Board} | {estado: "conflito" | "erro" | "ocupado"};

export function useBoardCriativo(canal: string) {
  const api = "/api/canais/" + encodeURIComponent(canal) + "/board";
  const [board, setBoard] = useState<Board | null>(null);
  const [falhaLeitura, setFalhaLeitura] = useState("");
  const [falhaAcao, setFalhaAcao] = useState<{mensagem: string; conflito: boolean; repetir?: boolean} | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const ativo = useRef<AbortController | null>(null);
  const gravando = useRef(false);
  const atual = useRef<Board | null>(null);
  atual.current = board;

  const carregar = useCallback(async (): Promise<Board | null> => {
    if (gravando.current) return null;
    ativo.current?.abort();
    const controle = new AbortController();
    ativo.current = controle;
    try {
      const resposta = await studioRequest<Board>(api, {signal: controle.signal});
      if (controle.signal.aborted) return null;
      setBoard(resposta);
      setFalhaLeitura("");
      return resposta;
    } catch (erro) {
      if (controle.signal.aborted) return null;
      if (erro instanceof ApiError && [401, 403, 404].includes(erro.failure.status)) setBoard(null);
      setFalhaLeitura(erro instanceof Error ? erro.message : "Falha ao carregar o rascunho.");
      return null;
    }
  }, [api]);

  useEffect(() => {
    void carregar();
    return () => ativo.current?.abort();
  }, [carregar]);

  const operacao = board?.operacao;
  useEffect(() => {
    if (!operacao) return;
    const consulta = window.setInterval(carregar, 2700);
    return () => window.clearInterval(consulta);
  }, [operacao, carregar]);

  const executar = useCallback(async (mudanca: ComandoBoard | PedidoBoard, revisao: number) => {
    if (gravando.current) return {ok: false as const, conflito: false, mensagem: ""};
    gravando.current = true;
    ativo.current?.abort();
    const controle = new AbortController();
    ativo.current = controle;
    setOcupado(true);
    const analisar = "tipo" in mudanca;
    try {
      const resposta = await studioRequest<Board>(api + (analisar ? "/analises" : ""), {
        method: analisar ? "POST" : "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({revisao, ...mudanca}),
        signal: controle.signal,
      });
      if (controle.signal.aborted) return {ok: false as const, conflito: false, mensagem: ""};
      setBoard(resposta);
      return {ok: true as const, board: resposta};
    } catch (erro) {
      return {
        ok: false as const,
        conflito: erro instanceof ApiError && erro.failure.code === "revisao_board",
        mensagem: controle.signal.aborted ? "" :
          erro instanceof Error ? erro.message : "O Studio não conseguiu salvar esta ação.",
      };
    } finally {
      gravando.current = false;
      if (!controle.signal.aborted) setOcupado(false);
    }
  }, [api]);

  const enviar = useCallback(async (mudanca: ComandoBoard | PedidoBoard, revisao: number): Promise<boolean> => {
    setFalhaAcao(null);
    const resultado = await executar(mudanca, revisao);
    if (!resultado.ok && resultado.mensagem) setFalhaAcao({mensagem: resultado.mensagem, conflito: resultado.conflito});
    return resultado.ok;
  }, [executar]);

  /** Grava a edição local só se a pauta salva ainda for a que a pessoa começou a editar. */
  const salvarPauta = useCallback(async (local: PautaBoard, base: PautaBoard | null): Promise<ResultadoPauta> => {
    setFalhaAcao(null);
    let referencia = atual.current;
    for (let tentativa = 0; tentativa < 2 && referencia; tentativa++) {
      if (!mesmaPauta(referencia.pauta, base)) return {estado: "conflito"};
      const resultado = await executar({acao: "pauta", pauta: local}, referencia.revisao);
      if (resultado.ok) return {estado: "salvo", board: resultado.board};
      if (!resultado.conflito) {
        if (!resultado.mensagem) return {estado: "ocupado"};
        setFalhaAcao({mensagem: resultado.mensagem, conflito: false});
        return {estado: "erro"};
      }
      referencia = await carregar();
    }
    return {estado: referencia ? "conflito" : "erro"};
  }, [carregar, executar]);

  const salvarAoSair = useCallback((local: PautaBoard, base: PautaBoard | null) => {
    const referencia = atual.current;
    if (!referencia || !mesmaPauta(referencia.pauta, base)) return;
    void fetch(api, {
      method: "PUT", keepalive: true, credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revisao: referencia.revisao, acao: "pauta", pauta: local}),
    }).catch(() => undefined);
  }, [api]);

  /** Repetir com a mesma revisão devolve a mesma execução: é seguro tentar de novo após falha de rede. */
  const aprovar = useCallback(async (revisao: number, fluxoId: string): Promise<string | null> => {
    if (gravando.current) return null;
    gravando.current = true;
    setFalhaAcao(null);
    setOcupado(true);
    try {
      const resposta = await studioRequest<{run_id: string; board: Board}>(api + "/aprovacoes", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({revisao, fluxo_id: fluxoId}),
      });
      setBoard(resposta.board);
      return resposta.run_id;
    } catch (erro) {
      const conflito = erro instanceof ApiError && erro.failure.code === "revisao_board";
      setFalhaAcao({
        mensagem: erro instanceof Error ? erro.message : "O Studio não conseguiu criar o roteiro.",
        conflito, repetir: !conflito && !(erro instanceof ApiError && erro.failure.status === 422),
      });
      return null;
    } finally {
      gravando.current = false;
      setOcupado(false);
    }
  }, [api]);

  async function recarregarRevisao() {
    setFalhaAcao(null);
    await carregar();
  }

  return {board, falhaLeitura, falhaAcao, ocupado, enviar, carregar, recarregarRevisao, salvarPauta, salvarAoSair, aprovar};
}
