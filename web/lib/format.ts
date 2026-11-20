/**
 * Formatação de datas e durações para o painel. A API devolve ISO-8601, mas
 * fixtures e projeções antigas às vezes trazem outra forma: tudo que não for
 * string parseável vira `null` e a tela mostra "—", nunca "Invalid Date".
 */

export function parseInstant(value: unknown): Date | null {
  if (typeof value !== "string" || value.length === 0) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatClock(value: unknown): string {
  const date = parseInstant(value);
  if (!date) return "—";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(value: unknown): string {
  const date = parseInstant(value);
  if (!date) return "—";
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "agora", "há 5 min", "há 3 h", "há 2 dias". */
export function formatRelative(value: unknown, now: Date = new Date()): string {
  const date = parseInstant(value);
  if (!date) return "—";
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (seconds < 45) return "agora";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "há 1 dia" : `há ${days} dias`;
}

/** Duração entre dois instantes: "42 s", "12 min", "1 h 05 min". */
export function formatDuration(start: unknown, end: unknown = null, now: Date = new Date()): string {
  const from = parseInstant(start);
  if (!from) return "—";
  const to = parseInstant(end) ?? now;
  const total = Math.max(0, Math.round((to.getTime() - from.getTime()) / 1000));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? id.slice(0, 8) : id;
}
