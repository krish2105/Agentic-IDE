import type { Timeline } from "./replay.ts";
import type {
  FileDiff,
  FileEntry,
  MissionControlRow,
  RagStatus,
  Session,
  TrustTier,
} from "./types.ts";

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
export interface ApiOptions {
  /** Bearer token, when the server has SANI_AUTH_TOKEN set. */
  token?: string | null;
  fetchImpl?: typeof fetch;
}

export function createApi(baseUrl: string, options: ApiOptions = {}) {
  const server = baseUrl.replace(/\/$/, "");
  const token = options.token?.trim() || null;
  const fetchImpl = options.fetchImpl ?? fetch;

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetchImpl(server + path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
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

    token,

    /**
     * A WebSocket URL, with the token in the query string when one is set.
     *
     * Browsers cannot set headers on a WebSocket handshake, so this is the
     * only mechanism available. It does put the token in URLs and access logs;
     * the alternative was leaving the terminal unauthenticated.
     */
    wsUrl(path: string): string {
      const base = server.replace(/^http/, "ws") + path;
      if (!token) return base;
      return base + (base.includes("?") ? "&" : "?") + `token=${encodeURIComponent(token)}`;
    },

    createSession: (input: CreateSessionInput) =>
      request<Session>("/session", { method: "POST", body: JSON.stringify(input) }),

    getSession: (id: string) => request<Session>(`/session/${id}`),

    missionControl: () =>
      request<{
        sessions: MissionControlRow[];
        active: number;
        awaiting_approval: number;
        store?: { kind: string; durable: boolean };
      }>("/mission-control"),

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

    /**
     * The replayable log plus its computed keyframes.
     *
     * Keyframes come from the server rather than being derived here: two
     * clients deciding independently what "mattered" in a run is two chances
     * to decide differently.
     */
    timeline: (id: string, fromSeq = 0) =>
      request<Timeline>(`/session/${id}/timeline?from_seq=${fromSeq}`),

    setTrust: (id: string, actionType: string, autoApprove: boolean) =>
      request<{ tiers: Record<string, TrustTier> }>(`/session/${id}/trust`, {
        method: "PATCH",
        body: JSON.stringify({ action_type: actionType, auto_approve: autoApprove }),
      }),

    /** Bytes URL for images -- screenshots and image diffs. */
    rawFileUrl: (id: string, path: string) => {
      // <img src> cannot carry an Authorization header either.
      const url = `${server}/session/${id}/file/raw?path=${encodeURIComponent(path)}`;
      return token ? `${url}&token=${encodeURIComponent(token)}` : url;
    },

    ragStatus: (sessionId: string) =>
      request<RagStatus>(`/rag/status?session_id=${encodeURIComponent(sessionId)}`),

    ragIndex: (sessionId: string) =>
      request<{ files: number; chunks: number; elapsed_s: number }>("/rag/index", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      }),

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
      request<{
        ok: boolean;
        version: string;
        protocol_version: number;
        auth?: { required: boolean; scheme: string };
        session_store?: { kind: string; durable: boolean };
      }>("/healthz"),
  };
}

export type SaniApi = ReturnType<typeof createApi>;
