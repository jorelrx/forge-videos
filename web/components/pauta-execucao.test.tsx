import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { RunView } from "../lib/contracts";
import { PautaExecucao } from "./pauta-execucao";

function view(extra: Record<string, unknown> = {}): RunView {
  return {
    run: {id: "r1", status: "paused", config_snapshot: {
      aguardando_editorial: "conflito_pauta",
      pauta_aprovada: {revisao: 7, titulo: "Adiar", promessa: "Adiar é preguiça", recorte: "A pia"}, ...extra,
    }},
    artifacts: [{id: "art-1", kind: "conflito_pauta", is_current: true, metadata: {
      explicacao: "A fonte liga adiar ao medo.", promessa_proposta: "Adiar como proteção",
      recorte_proposto: "O medo de ser avaliado",
      evidencias: [{path: "1/c1/p1", titulo: "Livro", trecho: "Adiar protege."}],
    }}],
  } as unknown as RunView;
}

it("conflito oferece aceitar, editar e cancelar", async () => {
  const decidir = vi.fn(async () => undefined);
  render(<PautaExecucao run={view()} decidir={decidir}/>);

  expect(screen.getByText("Adiar protege.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "Aceitar recorte proposto"}));
  await waitFor(() => expect(decidir).toHaveBeenCalledWith({artefato_id: "art-1", acao: "aceitar"}));
  fireEvent.click(screen.getByRole("button", {name: "Cancelar encaminhamento"}));
  await waitFor(() => expect(decidir).toHaveBeenCalledWith({artefato_id: "art-1", acao: "cancelar"}));
  fireEvent.click(screen.getByRole("button", {name: "Editar promessa ou recorte"}));
  fireEvent.change(screen.getByLabelText("Promessa"), {target: {value: "Adiar também protege"}});
  fireEvent.click(screen.getByRole("button", {name: "Salvar e continuar"}));
  await waitFor(() => expect(decidir).toHaveBeenLastCalledWith({
    artefato_id: "art-1", acao: "editar", promessa: "Adiar também protege", recorte: "O medo de ser avaliado",
  }));
});

it("mostra pauta original, decisão e recorte recebido", () => {
  const decidida = view({
    aguardando_editorial: undefined,
    pauta_decidida: {promessa: "Adiar como proteção", recorte: "O medo de ser avaliado"},
    decisao_pauta: {acao: "aceitar"},
  });
  render(<PautaExecucao run={{...decidida, run: {...decidida.run, status: "running"}} as RunView}/>);
  expect(screen.getByText("Adiar é preguiça")).toBeTruthy();
  expect(screen.getByText(/recorte proposto aceito/)).toBeTruthy();
  expect(screen.getByRole("heading", {name: "Recorte recebido pela escrita"})).toBeTruthy();
  expect(screen.queryByRole("button", {name: "Aceitar recorte proposto"})).toBeNull();
});
