import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ActiveRun, lastStageWithData, runKicker } from "./active-run";
import type { StageName } from "../lib/contracts";

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    run: { id: "run-1", status: "running", tema: "O tédio como alarme" },
    video: { tema: "O tédio como alarme" },
    progress: 0.42,
    current_stage: "pesquisa" as StageName | null,
    ...overrides,
  } as any;
}

describe("ActiveRun — kicker pelo status real", () => {
  const cases: [string, string][] = [
    ["queued", "Na fila"],
    ["preparing", "Run em execução"],
    ["running", "Run em execução"],
    ["validating", "Run em execução"],
    ["paused", "Run pausada"],
    ["interrupted", "Run interrompida"],
    ["failed", "Run falhou"],
    ["completed", "Run concluída"],
  ];

  it.each(cases)("status %s → kicker %s", (status, expected) => {
    render(
      <ActiveRun
        run={makeRun({ run: { id: "run-1", status } })}
        progressPercent={42}
      />,
    );
    expect(screen.getByText(expected)).not.toBeNull();
  });

  it("runKicker cai no fallback para status desconhecido", () => {
    expect(runKicker("cancelled")).toBe("Run cancelada");
    expect(runKicker(undefined)).toBe("Run");
  });

  it("não usa mais o kicker hardcoded de execução", () => {
    render(<ActiveRun run={makeRun({ run: { id: "run-1", status: "interrupted" } })} />);
    expect(screen.queryByText(/Run em execução/)).toBeNull();
  });
});

describe("ActiveRun — progresso", () => {
  it("mostra o percentual uma única vez", () => {
    render(<ActiveRun run={makeRun()} progressPercent={42} />);
    expect(screen.getAllByText("42%").length).toBe(1);
    expect(screen.getByText("concluído")).not.toBeNull();
  });

  it("deriva o percentual de progress quando não recebe progressPercent", () => {
    render(<ActiveRun run={makeRun({ progress: 0.13 })} />);
    expect(screen.getAllByText("13%").length).toBe(1);
  });
});

describe("ActiveRun — etapa atual", () => {
  it("usa current_stage quando presente", () => {
    render(<ActiveRun run={makeRun({ current_stage: "montagem" })} />);
    expect(screen.getByText("Etapa atual").parentElement?.textContent).toContain("Montagem");
  });

  it("deriva a última etapa com dados quando interrupted e current_stage nulo", () => {
    render(
      <ActiveRun
        run={makeRun({
          current_stage: null,
          run: { id: "run-1", status: "interrupted" },
          stages: {
            pesquisa: { stage_run: { status: "succeeded", started_at: "2026-09-14T00:00:00Z" } },
            roteiro: { stage_run: { status: "interrupted", started_at: "2026-09-14T00:05:00Z" } },
            montagem: { stage_run: { status: "pending", started_at: null } },
          },
        })}
      />,
    );
    expect(screen.getByText("Etapa atual").parentElement?.textContent).toContain("Roteiro");
  });

  it("mantém '—' quando não há etapas com dados", () => {
    render(
      <ActiveRun
        run={makeRun({
          current_stage: null,
          run: { id: "run-1", status: "interrupted" },
        })}
      />,
    );
    expect(screen.getByText("Etapa atual").parentElement?.textContent).toContain("—");
  });

  it("lastStageWithData ignora stage_run sem atividade", () => {
    expect(
      lastStageWithData({
        pesquisa: { stage_run: { status: "succeeded", started_at: "x" } },
        audio: { stage_run: { status: "pending", started_at: null } },
      }),
    ).toBe("pesquisa");
    expect(lastStageWithData(undefined)).toBeNull();
  });
});
