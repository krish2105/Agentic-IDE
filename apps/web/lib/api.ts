import type { FileDiff, FileEntry, MissionControlRow, Session } from "./types";

export const SERVER =
  process.env.NEXT_PUBLIC_SANI_SERVER?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export function wsUrl(path: string): string {
  return SERVER.replace(/^http/, "ws") + path;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(SERVER + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    let code = "http_error";
    let detail = response.statusText;
    try {
      const body = await response.json();
      code = body.error ?? code;
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body; the status line is all we have */
    }
    throw new ApiError(response.status, code, detail);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export interface CreateSessionInput {
  task: string;
  workspace?: string;
  lifecycle?: "foreground" | "background";
  trust_overrides?: Record<string, boolean>;
  script?: unknown[];
}

export const api = {
  createSession: (input: CreateSessionInput) =>
    request<Session>("/session", { method: "POST", body: JSON.stringify(input) }),

  getSession: (id: string) => request<Session>(`/session/${id}`),

  missionControl: () =>
    request<{ sessions: MissionControlRow[]; active: number; awaiting_approval: number }>(
      "/mission-control",
    ),

  approve: (id: string, actionId: string, hunkIds?: string[] | null) =>
    request<Record<string, unknown>>(`/session/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId, hunk_ids: hunkIds ?? null }),
    }),

  reject: (id: string, actionId: string, reason?: string) =>
    request<Record<string, unknown>>(`/session/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId, reason: reason ?? null }),
    }),

  pause: (id: string) => request(`/session/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request(`/session/${id}/resume`, { method: "POST" }),
  kill: (id: string) => request<Session>(`/session/${id}/kill`, { method: "POST" }),

  diff: (id: string) => request<{ files: FileDiff[] }>(`/session/${id}/diff`),

  files: (id: string) =>
    request<{ workspace: string; entries: FileEntry[] }>(`/session/${id}/files`),

  readFile: (id: string, path: string) =>
    request<{ path: string; content: string | null; binary?: boolean; too_large?: boolean }>(
      `/session/${id}/file?path=${encodeURIComponent(path)}`,
    ),

  saveFile: (id: string, path: string, content: string) =>
    request<{ saved: boolean }>(`/session/${id}/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    }),

  health: () => request<{ ok: boolean; version: string; protocol_version: number }>("/healthz"),
};
