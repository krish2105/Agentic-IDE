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

  // The browser only sends the token on a real request; a preflight OPTIONS is
  // enough to see whether the origin is allowed at all.
  const response = await fetch(`${SERVER}/mission-control`, {
    headers: { Origin: WEB },
  });
  const allowed = response.headers.get("access-control-allow-origin");
  if (allowed !== WEB && allowed !== "*") {
    throw new Error(
      `The server does not allow requests from ${WEB} (Access-Control-Allow-Origin: ${allowed ?? "absent"}).\n` +
        `  Every fetch from the page will be blocked while the WebSocket keeps working, which looks like broken UI.\n` +
        `  Restart the server with: SANI_CORS_ORIGINS=${WEB} uv run uvicorn sani_server.app:app --port ${new URL(SERVER).port}`,
    );
  }
}
