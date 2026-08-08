import type { FileDiff, FileEntry, MissionControlRow, Session } from "./types.ts";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export interface CreateSessionInput {
  task: string;
  workspace?: string;
  lifecycle?: "foreground" | "background";
  trust_overrides?: Record<string, boolean>;
  script?: unknown[];
}

/**
 * The server's HTTP surface, as a factory rather than a module singleton.
 *
 * Both clients learn their base URL differently -- the web app from a build
 * time env var, the extension from a workspace setting -- so the base URL is a
 * parameter and neither surface's mechanism leaks into the shared code.
 */
export function createApi(baseUrl: string, fetchImpl: typeof fetch = fetch) {
  const server = baseUrl.replace(/\/$/, "");

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetchImpl(server + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });

    if (!response.ok) {
      let code = "http_error";
      let detail = response.statusText;
      try {
        const body: any = await response.json();
        code = body.error ?? code;
        detail = body.detail ?? detail;
      } catch {
        /* non-JSON error body; the status line is all we have */
      }
      throw new ApiError(response.status, code, detail);
    }

    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  }

  return {
    server,

    wsUrl(path: string): string {
      return server.replace(/^http/, "ws") + path;
    },

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
      request<{
        path: string;
        content: string | null;
        binary?: boolean;
        too_large?: boolean;
      }>(`/session/${id}/file?path=${encodeURIComponent(path)}`),

    saveFile: (id: string, path: string, content: string) =>
      request<{ saved: boolean }>(`/session/${id}/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content }),
      }),

    health: () =>
      request<{ ok: boolean; version: string; protocol_version: number }>("/healthz"),
  };
}

export type SaniApi = ReturnType<typeof createApi>;
