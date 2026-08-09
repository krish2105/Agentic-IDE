"use client";

import {
  createApi,
  diagnoseConnection,
  explainProblem,
  normalizeServerUrl,
  type ConnectionProblem,
  type SaniApi,
} from "@sani/client";

/**
 * Where this build points, and how to change it without rebuilding.
 *
 * `NEXT_PUBLIC_SANI_SERVER` is inlined at build time, which is fine for a
 * local checkout and actively wrong for a hosted one: a deploy compiled
 * against the default calls `127.0.0.1:8000`, which in a visitor's browser
 * means *their own machine*. That is the entire reason a hosted build shows
 * "cannot reach the server" no matter what is running.
 *
 * So the build-time value is only a default. Whatever the user configures at
 * runtime wins, and is kept in localStorage, so one deployment can point at
 * any backend.
 */
export const BUILD_TIME_SERVER =
  process.env.NEXT_PUBLIC_SANI_SERVER?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const SERVER_KEY = "sani.serverUrl";
const TOKEN_KEY = "sani.authToken";

export interface Connection {
  server: string;
  token: string;
}

function read(key: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return ""; // private browsing, storage disabled
  }
}

export function currentConnection(): Connection {
  return {
    server: read(SERVER_KEY) || BUILD_TIME_SERVER,
    token: read(TOKEN_KEY),
  };
}

/**
 * Why the connection is failing. The logic is in @sani/client so it is unit
 * tested; this only supplies the page URL the browser is actually on.
 */
export function diagnose(server: string, status?: number | null): ConnectionProblem {
  return diagnoseConnection({
    server,
    pageUrl: typeof window === "undefined" ? "http://localhost/" : window.location.href,
    status,
  });
}

export { explainProblem };
export type { ConnectionProblem };

let active = createApi(BUILD_TIME_SERVER);
const listeners = new Set<() => void>();

function rebuild(): void {
  const { server, token } = currentConnection();
  active = createApi(server, { token });
  for (const listener of listeners) listener();
}

if (typeof window !== "undefined") rebuild();

export function onConnectionChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function saveConnection({ server, token }: Connection): void {
  try {
    // Normalised on the way *in*, not just when a request is built, so the
    // stored value and the value shown back to the user are the real one. A
    // host pasted without a scheme would otherwise sit in storage looking
    // correct while resolving relative to this page.
    const trimmed = normalizeServerUrl(server);
    if (trimmed) window.localStorage.setItem(SERVER_KEY, trimmed);
    else window.localStorage.removeItem(SERVER_KEY);

    if (token.trim()) window.localStorage.setItem(TOKEN_KEY, token.trim());
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable; the in-memory client below still updates */
  }
  rebuild();
}

/**
 * A stable handle that always forwards to the currently configured client, so
 * changing the connection does not require every call site to re-import.
 */
export const api = new Proxy({} as SaniApi, {
  get: (_target, property) => (active as unknown as Record<string, unknown>)[property as string],
}) as SaniApi;

export function wsUrl(path: string): string {
  return active.wsUrl(path);
}

export { ApiError } from "@sani/client";
