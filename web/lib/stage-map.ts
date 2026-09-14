import type { StageName } from "./contracts";

export function stageStatus(stage: StageName): string {
  return ({
    preparacao: "Preparação",
    pesquisa: "Pesquisa",
    roteiro: "Roteiro",
    plano_midia: "Plano de mídia",
    audio: "Áudio",
    imagens: "Imagens",
    montagem: "Montagem",
    validacao: "Validação",
  }[stage] ?? stage);
}

export function serviceStatusLabel(status: string): string {
  return ({
    queued: "Na fila",
    preparing: "Preparando",
    running: "Em execução",
    pausing: "Pausando",
    paused: "Pausado",
    validating: "Validando",
    completed: "Concluído",
    failed: "Falhou",
    interrupted: "Interrompido",
    cancelled: "Cancelado",
  }[status] ?? status);
}
