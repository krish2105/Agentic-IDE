/**
 * Fail fast on a misconfigured harness.
 *
 * Every environmental mistake in this suite fails the same way: a selector
 * times out after 60 seconds and points at a component that was never the
 * problem. Two have cost real time:
 *
 *  - **CORS.** The server allows `localhost:3000` by default. Point the tests
 *    at any other port and every `fetch` is blocked while the WebSocket, which
 *    is not CORS-checked, keeps working -- so the plan renders, the status pill
 *    updates, and only the file tree, trust panel and diff list are silently
 *    empty. That reads exactly like a broken component.
 *  - **Next dev origins.** Next 16 serves `/_next/static/*` only to hosts in
 *    `allowedDevOrigins`. A blocked host 403s every chunk, so the page
 *    server-renders and never hydrates -- nothing is clickable and the DOM
 *    looks right.
 *
 * Both are one HTTP request to detect. Detecting them here turns a confusing
 * three-minute red suite into a two-second error that names the fix.
 */

export const SERVER = process.env.SANI_SERVER_URL ?? "http://127.0.0.1:8000";
export const WEB = process.env.SANI_WEB_URL ?? "http://127.0.0.1:3000";

/**
 * Set when the server under test has `SANI_AUTH_TOKEN`.
 *
 * Empty is the normal local case and stays the default. It matters because the
 * moment the backend is exposed over a tunnel it *must* have a token -- the
 * shell adapter executes commands -- and the suite should keep working against
 * that server rather than only against an open one.
 */
export const TOKEN = process.env.SANI_AUTH_TOKEN ?? "";

/** Headers a request needs to be let through. */
export function authHeaders(): Record<string, string> {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

/** Seeds the app's own runtime connection settings, as the page would store
 *  them. Used by every spec's `beforeEach`. */
export const CONNECTION = { server: SERVER, token: TOKEN };

async function reachable(url: string, what: string, hint: string): Promise<void> {
  try {
    await fetch(url);
  } catch {
    throw new Error(`${what} is not reachable at ${url}.\n  ${hint}`);
  }
}

export async function preflight(): Promise<void> {
  await reachable(
    `${SERVER}/healthz`,
    "The Sani server",
    `Start it with: SANI_CORS_ORIGINS=${WEB} uv run uvicorn sani_server.app:app --port ${new URL(SERVER).port}`,
  );
  await reachable(WEB, "The web IDE", `Start it with: npm run dev --workspace sani-web`);

  // Auth middleware sits *outside* CORS on purpose -- it has to, or the
  // WebSocket routes would be unguarded -- so an unauthenticated 401 carries no
  // CORS headers at all. Sending the token first keeps this check measuring the
  // thing it is named after rather than reporting a CORS fault for a missing
  // token.
  const response = await fetch(`${SERVER}/mission-control`, {
    headers: { Origin: WEB, ...authHeaders() },
  });
  if (response.status === 401) {
    throw new Error(
      `The server rejected the token (401).\n` +
        `  It has SANI_AUTH_TOKEN set; run the suite with the same value in SANI_AUTH_TOKEN.`,
    );
  }
  // Most specs pin `model_backend: "scripted"` per session, but the first
  // ide.spec test creates its session through the UI and so inherits the
  // server's default. Against a litellm server the plan is whatever the model
  // says, there is no guaranteed `file.delete` to gate on, and the failure is a
  // selector timeout on `approval-card` — which looks like a broken approval
  // gate rather than a server configured for real use.
  const health = await fetch(`${SERVER}/healthz`).then((r) => r.json());
  if (health?.model && health.model.scripted !== true) {
    throw new Error(
      `The server is running the '${health.model.backend}' backend.\n` +
        `  This suite asserts against the scripted planner's fixed plan, so a real model makes it fail\n` +
        `  on selectors that are not broken. Restart without a Groq key, or:\n` +
        `      SANI_MODEL_BACKEND=scripted uv run uvicorn sani_server.app:app --port ${new URL(SERVER).port}`,
    );
  }

  const allowed = response.headers.get("access-control-allow-origin");
  if (allowed !== WEB && allowed !== "*") {
    throw new Error(
      `The server does not allow requests from ${WEB} (Access-Control-Allow-Origin: ${allowed ?? "absent"}).\n` +
        `  Every fetch from the page will be blocked while the WebSocket keeps working, which looks like broken UI.\n` +
        `  Restart the server with: SANI_CORS_ORIGINS=${WEB} uv run uvicorn sani_server.app:app --port ${new URL(SERVER).port}`,
    );
  }
}
