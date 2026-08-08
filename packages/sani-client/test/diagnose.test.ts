import assert from "node:assert/strict";
import { test } from "node:test";
import {
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
