"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, studioRequest } from "../lib/api";
import type { Board, ComandoBoard, PedidoBoard } from "../lib/board-criativo";

export function useBoardCriativo(canal: string) {
  const api = "/api/canais/" + encodeURIComponent(canal) + "/board";
  const [board, setBoard] = useState<Board | null>(null);
  const [falhaLeitura, setFalhaLeitura] = useState("");
  const [falhaAcao, setFalhaAcao] = useState<{mensagem: string; conflito: boolean} | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const ativo = useRef<AbortController | null>(null);
  const gravando = useRef(false);

  const carregar = useCallback(async () => {
    if (gravando.current) return;
    ativo.current?.abort();
    const controle = new AbortController();
    ativo.current = controle;
    try {
      const resposta = await studioRequest<Board>(api, {signal: controle.signal});
      if (!controle.signal.aborted) {
        setBoard(resposta);
        setFalhaLeitura("");
      }
    } catch (erro) {
      if (controle.signal.aborted) return;
      if (erro instanceof ApiError && [401, 403, 404].includes(erro.failure.status)) setBoard(null);
      setFalhaLeitura(erro instanceof Error ? erro.message : "Falha ao carregar o rascunho.");
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

  const enviar = useCallback(async (mudanca: ComandoBoard | PedidoBoard, revisao: number): Promise<boolean> => {
    if (gravando.current) return false;
    gravando.current = true;
    ativo.current?.abort();
    const controle = new AbortController();
    ativo.current = controle;
    setFalhaAcao(null);
    setOcupado(true);
    const analisar = "tipo" in mudanca;
    try {
      const resposta = await studioRequest<Board>(api + (analisar ? "/analises" : ""), {
        method: analisar ? "POST" : "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({revisao, ...mudanca}),
        signal: controle.signal,
      });
      if (controle.signal.aborted) return false;
      setBoard(resposta);
      return true;
    } catch (erro) {
      if (!controle.signal.aborted) {
        setFalhaAcao({
          mensagem: erro instanceof Error ? erro.message : "O Studio não conseguiu salvar esta ação.",
          conflito: erro instanceof ApiError && erro.failure.code === "revisao_board",
        });
      }
      return false;
    } finally {
      gravando.current = false;
      if (!controle.signal.aborted) setOcupado(false);
    }
  }, [api]);

  async function recarregarRevisao() {
    setFalhaAcao(null);
    await carregar();
  }

  return {board, falhaLeitura, falhaAcao, ocupado, enviar, carregar, recarregarRevisao};
}
