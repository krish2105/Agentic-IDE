import { createApi } from "@sani/client";

/**
 * `NEXT_PUBLIC_*` is inlined at build time, so this must be a literal property
 * access rather than a dynamic lookup -- and it is the one Next-specific thing
 * the client layer knows. Everything else lives in @sani/client, shared with
 * the VS Code extension.
 */
export const SERVER =
  process.env.NEXT_PUBLIC_SANI_SERVER?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export const api = createApi(SERVER);

export function wsUrl(path: string): string {
  return api.wsUrl(path);
}

export { ApiError } from "@sani/client";
