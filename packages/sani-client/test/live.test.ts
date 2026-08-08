/**
 * The shared client against a real server, over a real WebSocket.
 *
 * This is the exact code path the VS Code extension runs -- `createApi` plus
 * `SessionStream` driven by the `ws` package -- with only the editor glue
 * removed. The unit tests prove the reducer with a fake socket; this proves the
 * whole client actually talks to the server.
 *
 * Skips itself when no server is listening, so `npm test` stays offline-safe.
 *   uv run uvicorn sani_server.app:app --port 8000
 */

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import WebSocket from "ws";
import { createApi } from "../src/api.ts";
import { SessionStream } from "../src/session-stream.ts";
import type { StreamState } from "../src/stream.ts";

const SERVER = process.env.SANI_SERVER_URL ?? "http://127.0.0.1:8000";
const api = createApi(SERVER);

async function serverIsUp(): Promise<boolean> {
  try {
    await api.health();
    return true;
  } catch {
    return false;
  }
}

function makeWorkspace(): string {
  const dir = mkdtempSync(join(tmpdir(), "sani-live-"));
  writeFileSync(join(dir, "README.md"), "# Demo project\n");
  writeFileSync(join(dir, "scratch.tmp"), "left over\n");
  return dir;
}

function openStream(sessionId: string): SessionStream {
  return new SessionStream(
    api.wsUrl(`/session/${sessionId}/stream`),
    (url) => new WebSocket(url) as never,
  );
}

function until(
  stream: SessionStream,
  predicate: (state: StreamState) => boolean,
  what: string,
  timeoutMs = 20_000,
): Promise<StreamState> {
  return new Promise((resolve, reject) => {
    const finish = (fn: () => void) => {
      clearTimeout(timer);
      unsubscribe();
      fn();
    };
    const timer = setTimeout(
      () => finish(() => reject(new Error(`timed out waiting for ${what}`))),
      timeoutMs,
    );
    const unsubscribe = stream.subscribe((state) => {
      if (predicate(state)) finish(() => resolve(state));
    });
    if (predicate(stream.getState())) finish(() => resolve(stream.getState()));
  });
}

const skip = !(await serverIsUp());

test(
  "a live session blocks on the always-confirm delete and completes once approved",
  { skip: skip && "no server on " + SERVER },
  async () => {
    const workspace = makeWorkspace();
    const session = await api.createSession({ task: "add a greeting module", workspace });
    const stream = openStream(session.session_id);

    try {
      stream.connect();

      const blocked = await until(
        stream,
        (state) => state.status === "blocked-on-approval",
        "the delete to block",
      );

      assert.equal(blocked.pending?.action.action_type, "file.delete");
      assert.equal(blocked.steps.length, 3);
      assert.ok(blocked.chat.some((item) => item.kind === "message"), "plan should be streamed");
      assert.ok(existsSync(join(workspace, "greeting.py")), "the auto-approved write ran");
      assert.ok(existsSync(join(workspace, "scratch.tmp")), "the gated delete did not");
      assert.ok(blocked.diffs["greeting.py"], "the write produced a diff");

      await api.approve(session.session_id, blocked.pending!.action.id);

      const done = await until(stream, (state) => state.ended, "the session to finish");
      assert.equal(done.status, "complete");
      assert.ok(!existsSync(join(workspace, "scratch.tmp")), "the approved delete ran");
      assert.deepEqual(
        done.steps.map((step) => step.status),
        ["complete", "complete", "complete"],
      );
    } finally {
      stream.dispose();
    }
  },
);

test(
  "reconnecting mid-run replays exactly what was missed",
  { skip: skip && "no server on " + SERVER },
  async () => {
    const workspace = makeWorkspace();
    const session = await api.createSession({ task: "reconnect check", workspace });

    const first = openStream(session.session_id);
    first.connect();
    const early = await until(first, (state) => state.steps.length > 0, "the plan");
    const seenSeq = early.lastSeq;
    first.dispose();

    // A fresh stream starting from zero must land on the same picture.
    const second = openStream(session.session_id);
    try {
      second.connect();
      const blocked = await until(
        second,
        (state) => state.status === "blocked-on-approval",
        "the block after reattach",
      );
      assert.ok(blocked.lastSeq > seenSeq);
      assert.equal(blocked.steps.length, 3);

      await api.reject(session.session_id, blocked.pending!.action.id, "not this time");
      const done = await until(second, (state) => state.ended, "completion");
      assert.equal(done.steps[2].status, "rejected");
      assert.ok(existsSync(join(workspace, "scratch.tmp")));
    } finally {
      second.dispose();
    }
  },
);

test(
  "the client reports where a shell command will run before it is approved",
  { skip: skip && "no server on " + SERVER },
  async () => {
    const workspace = makeWorkspace();
    const session = await api.createSession({
      task: "run a command",
      workspace,
      trust_overrides: { "shell.other": true },
      script: [
        { description: "say hello", tool: "shell", params: { command: "echo hello-from-live" } },
      ],
    });
    const stream = openStream(session.session_id);

    try {
      stream.connect();
      const done = await until(stream, (state) => state.ended, "the command to finish");

      const proposal = done.chat.find((item) => item.kind === "proposal");
      assert.equal(proposal?.runsIn, "host", "the local sandbox must not claim isolation");

      const result = done.chat.find((item) => item.kind === "result");
      assert.ok(result?.detail?.includes("hello-from-live"));
    } finally {
      stream.dispose();
    }
  },
);
