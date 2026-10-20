import type { Club, Fan, MatchState, Mode } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  league: () => req<{ name: string; clubs: Club[] }>("/api/league"),
  health: () => req<any>("/api/health"),
  table: () => req<any[]>("/api/table"),
  match: (id: string) => req<MatchState>(`/api/matches/${id}`),
  pitchControl: (id: string) => req<any>(`/api/matches/${id}/pitch-control?full=true`),
  explain: (momentId: string) => req<any>(`/api/moments/${momentId}/explain`),
  createFan: (body: { favorite_club: string; mode: Mode; language: string; display_name: string }) =>
    req<Fan>("/api/fans", { method: "POST", body: JSON.stringify(body) }),
  getFan: (id: string) => req<Fan>(`/api/fans/${id}`),
  patchFan: (id: string, body: Partial<Pick<Fan, "mode" | "language" | "captain" | "focus_player" | "favorite_club">>) =>
    req<Fan>(`/api/fans/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  feedback: (id: string, signal: string, kind: string, moment_id?: string) =>
    req<any>(`/api/fans/${id}/feedback`, { method: "POST", body: JSON.stringify({ signal, kind, moment_id }) }),
  rundown: (id: string) => req<any>(`/api/fans/${id}/rundown`, { method: "POST" }),
  ask: (question: string, fan_id?: string, match_id?: string | null) =>
    req<{ answer: string; tool_calls: { tool: string; args: any; ms: number }[]; latency_ms: number }>("/api/ask", {
      method: "POST",
      body: JSON.stringify({ question, fan_id, match_id }),
    }),
  restart: (matchday: number, speed: number) =>
    req<any>(`/api/admin/restart?matchday=${matchday}&speed=${speed}`, { method: "POST" }),
  speed: (speed: number) => req<any>(`/api/admin/speed?speed=${speed}`, { method: "POST" }),
};
