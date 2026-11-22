"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useDashboard, type DashboardState } from "../hooks/use-dashboard";
import { createStudioApi, type StudioApi } from "../lib/api";

interface DashboardShared {
  state: DashboardState;
  api: StudioApi;
}

const DashboardContext = createContext<DashboardShared | null>(null);

/**
 * Projeção do painel (fila, serviços, fluxo SSE da atividade) no layout do
 * canal. A produção é uma rota própria: guardado na página, esse estado
 * desmontava a cada ida a Vídeos e insights, e a volta refazia a sondagem de
 * serviços (~3 s) e reabria o SSE com a atividade vazia. No layout ele vive
 * enquanto o canal estiver aberto, como no painel único de antes.
 */
export function DashboardProvider({
  api,
  eventSource,
  children,
}: {
  api?: StudioApi;
  eventSource?: typeof EventSource;
  children: ReactNode;
}) {
  const studioApi = useMemo(() => api ?? createStudioApi(), [api]);
  const state = useDashboard(studioApi, { EventSource: eventSource });
  return <DashboardContext.Provider value={{ state, api: studioApi }}>{children}</DashboardContext.Provider>;
}

export function useSharedDashboard(): DashboardShared | null {
  return useContext(DashboardContext);
}
