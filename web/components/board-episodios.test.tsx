import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EpisodiosBoard } from "./board-episodios";
import type { EpisodioBoard } from "../lib/board-criativo";

const base: EpisodioBoard = {
  aprovacao_id: "a1", revisao: 9, titulo: "Um ensaio", run_id: "run-7", run_status: "completed",
  momento: "janela_completa", publicar_em: null, video_id: "vid", publicado_em: "2026-11-10T15:00:00Z",
  abertura: "Abre na pia", promessa: "Entender", url: "/canais/A/videos/vid?inicio=2026-10-25&fim=2026-11-21",
  janelas: {
    d7: {completa: true, fim: "2026-11-16", observacoes: [{medida: "views", valor: 340, unidade: "visualizações"} as never]},
    d28: {completa: false, fim: "2026-12-07", observacoes: []},
  },
};

it("episódio com janela completa mostra D+7 e leva ao resultado", () => {
  render(<EpisodiosBoard canal="A" episodios={[base]}/>);
  expect(screen.getByText("D+7 completa · 340 visualizações")).toBeTruthy();
  expect(screen.getByText("D+28 pendente até 07/12/2026")).toBeTruthy();
  expect(screen.getByRole("link", {name: "Ver resultado"}).getAttribute("href")).toBe(base.url + "#janelas");
  expect(screen.getByRole("link", {name: "Ver execução"}).getAttribute("href")).toBe("/canais/A/producao#/producao?run=run-7");
});

it("episódio agendado não mostra janelas nem resultado", () => {
  render(<EpisodiosBoard canal="A" episodios={[{...base, momento: "agendado", publicado_em: null, janelas: null,
    url: null, publicar_em: "2026-12-01T21:00:00Z"}]}/>);
  expect(screen.getByText(/Agendado no YouTube para 01\/12\/2026/)).toBeTruthy();
  expect(screen.queryByRole("link", {name: "Ver resultado"})).toBeNull();
});
