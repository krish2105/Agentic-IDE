import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi, normalizeServerUrl } from "../src/api.ts";

/**
 * A bare host, pasted into the connection panel, used to break the whole app in
 * the most misleading way available: every request resolved *relative to the
 * page*, 404'd, and the UI reported "cannot reach the server" — so you went and
 * debugged a server that was working perfectly.
 *
 * The UI invites the mistake, which is what makes it worth a test rather than a
 * doc note: the header renders the server with its scheme stripped for
 * legibility, so copying what is on screen and pasting it back is exactly how
 * you end up here.
 */

test("a bare host gets https, because a remote tunnel is always TLS", () => {
  assert.equal(
    normalizeServerUrl("exploring-writers.trycloudflare.com"),
    "https://exploring-writers.trycloudflare.com",
  );
  assert.equal(normalizeServerUrl("api.example.com/base"), "https://api.example.com/base");
});

test("loopback gets http, because a local dev server is not running TLS", () => {
  assert.equal(normalizeServerUrl("localhost:8060"), "http://localhost:8060");
  assert.equal(normalizeServerUrl("127.0.0.1:8060"), "http://127.0.0.1:8060");
  assert.equal(normalizeServerUrl("[::1]:8060"), "http://[::1]:8060");
});

test("an explicit scheme is never second-guessed", () => {
  assert.equal(normalizeServerUrl("http://127.0.0.1:8060"), "http://127.0.0.1:8060");
  assert.equal(normalizeServerUrl("https://localhost:8443"), "https://localhost:8443");
  // Even a deliberately odd one: overriding it would be worse than obeying it.
  assert.equal(normalizeServerUrl("http://api.example.com"), "http://api.example.com");
});

test("whitespace and trailing slashes are stripped", () => {
  assert.equal(normalizeServerUrl("  https://x.example.com/  "), "https://x.example.com");
  assert.equal(normalizeServerUrl("x.example.com///"), "https://x.example.com");
});

test("empty stays empty, so the build-time default can take over", () => {
  assert.equal(normalizeServerUrl(""), "");
  assert.equal(normalizeServerUrl("   "), "");
});

test("createApi normalizes, so a bare host reaches the right origin", async () => {
  const seen: string[] = [];
  const api = createApi("tunnel.example.com", {
    token: "t0ken",
    fetchImpl: (async (url: string) => {
      seen.push(String(url));
      return new Response(JSON.stringify({ sessions: [], active: 0, awaiting_approval: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch,
  });

  await api.missionControl();
  assert.equal(seen[0], "https://tunnel.example.com/mission-control");
  // Not a relative path, which is the bug: that resolves against the page.
  assert.ok(!seen[0].startsWith("tunnel.example.com"));
});

test("the websocket URL is derived from the normalized value too", () => {
  const remote = createApi("tunnel.example.com", { token: "t0ken" });
  assert.equal(
    remote.wsUrl("/session/ses_1/stream"),
    "wss://tunnel.example.com/session/ses_1/stream?token=t0ken",
  );

  const local = createApi("localhost:8060");
  assert.equal(local.wsUrl("/session/ses_1/stream"), "ws://localhost:8060/session/ses_1/stream");
});
