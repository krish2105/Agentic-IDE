import assert from "node:assert/strict";
import { test } from "node:test";
import {
  credentialWarning,
  diagnoseConnection,
  explainProblem,
  isHostedPage,
  isInsecureMix,
  isLoopback,
} from "../src/diagnose.ts";

const VERCEL = "https://agentic-ide-web.vercel.app/";
const LOCAL = "http://localhost:3000/";

test("loopback hosts are recognised in every spelling", () => {
  for (const host of ["localhost", "127.0.0.1", "[::1]", "0.0.0.0"]) {
    assert.equal(isLoopback(host), true, host);
  }
  assert.equal(isLoopback("agentic-ide-web.vercel.app"), false);
});

test("a hosted page is told apart from a local one", () => {
  assert.equal(isHostedPage(VERCEL), true);
  assert.equal(isHostedPage(LOCAL), false);
  assert.equal(isHostedPage("http://127.0.0.1:3000/"), false);
});

test("the hosted-build-pointing-at-localhost case is named exactly", () => {
  // This is the failure a Vercel deploy shows by default: the bundle was
  // compiled with the fallback NEXT_PUBLIC_SANI_SERVER still in place.
  assert.equal(
    diagnoseConnection({ server: "http://127.0.0.1:8000", pageUrl: VERCEL }),
    "loopback-from-hosted",
  );
  assert.match(
    explainProblem("loopback-from-hosted", "http://127.0.0.1:8000"),
    /your own machine/,
  );
});

test("an https page pointing at an http backend is a mixed-content problem", () => {
  assert.equal(
    diagnoseConnection({ server: "http://sani.example.com", pageUrl: VERCEL }),
    "insecure-mix",
  );
  assert.equal(isInsecureMix("https://sani.example.com", VERCEL), false);
});

test("a hosted page on an https tunnel gets no false alarm", () => {
  assert.equal(
    diagnoseConnection({ server: "https://abc.trycloudflare.com", pageUrl: VERCEL }),
    "unreachable",
  );
});

test("a purely local setup keeps the advice that actually helps", () => {
  assert.equal(
    diagnoseConnection({ server: "http://127.0.0.1:8000", pageUrl: LOCAL }),
    "unreachable",
  );
  assert.match(explainProblem("unreachable", "http://127.0.0.1:8000"), /Cannot reach/);
});

test("a 401 outranks every other diagnosis", () => {
  // Otherwise a hosted page with a bad token would be told to fix its URL.
  assert.equal(
    diagnoseConnection({ server: "http://127.0.0.1:8000", pageUrl: VERCEL, status: 401 }),
    "unauthorized",
  );
  assert.match(explainProblem("unauthorized", "https://x"), /auth token/);
});

test("a malformed server URL does not throw", () => {
  assert.equal(
    diagnoseConnection({ server: "not a url", pageUrl: VERCEL }),
    "unreachable",
  );
});

test("a URL pasted into the token field is called out", () => {
  // The failure this prevents: endless 401s that look exactly like a stale
  // token, so you keep re-fixing the server field and nothing changes.
  assert.match(
    credentialWarning({ server: "https://x.trycloudflare.com", token: "https://x.trycloudflare.com" })!,
    /looks like a URL/,
  );
});

test("a model provider key in the token field is called out", () => {
  const warning = credentialWarning({ server: "https://x.trycloudflare.com", token: "gsk_abc123" });
  assert.match(warning!, /model provider API key/);
  assert.match(credentialWarning({ server: "https://x.y", token: "sk-abc123" })!, /model provider/);
});

test("a token pasted into the server field is called out", () => {
  assert.match(
    credentialWarning({ server: "IYXkVzvAhEiB9J3l9KjGVFciGjmGonxP990RIV7s", token: "" })!,
    /looks like a token/,
  );
});

test("a correct pair warns about nothing", () => {
  assert.equal(
    credentialWarning({
      server: "https://exploring-writers.trycloudflare.com",
      token: "IYXkVzvAhEiB9J3l9KjGVFciGjmGonxP990RIV7s",
    }),
    null,
  );
  // An empty token is the normal local case, not a mistake.
  assert.equal(credentialWarning({ server: "http://127.0.0.1:8060", token: "" }), null);
});
