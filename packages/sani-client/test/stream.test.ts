import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionStream, type SocketLike } from "../src/session-stream.ts";
import { initialStreamState, reduceEvent, type StreamState } from "../src/stream.ts";
import type { SaniEvent } from "../src/types.ts";

let seq = 0;
function event(type: string, data: any = {}, override?: number): SaniEvent {
  return {
    v: 1,
    seq: override ?? ++seq,
    session_id: "ses_test",
    ts: 0,
    type: type as SaniEvent["type"],
    data,
  };
}

function fold(events: SaniEvent[], from: StreamState = initialStreamState): StreamState {
  return events.reduce(reduceEvent, from);
}

test.beforeEach(() => {
  seq = 0;
});

test("status events drive the session status", () => {
  const state = fold([
    event("session.status", { status: "planning" }),
    event("session.status", { status: "executing" }),
  ]);
  assert.equal(state.status, "executing");
});

test("message deltas accumulate then flush into the chat feed", () => {
  let state = fold([
    event("agent.message.delta", { text: "Reading " }),
    event("agent.message.delta", { text: "the README." }),
  ]);
  assert.equal(state.streamingMessage, "Reading the README.");
  assert.equal(state.chat.length, 0);

  state = reduceEvent(state, event("agent.message.done", { text: "Reading the README." }));
  assert.equal(state.streamingMessage, "");
  assert.deepEqual(
    state.chat.map((item) => item.kind),
    ["message"],
  );
});

test("an already-applied event is ignored, so replay is idempotent", () => {
  const first = fold([event("session.status", { status: "executing" })]);
  const replayed = reduceEvent(first, event("session.status", { status: "planning" }, 1));

  assert.equal(replayed, first, "the same state object should come back unchanged");
  assert.equal(replayed.status, "executing");
});

test("a reconnect that overlaps applies each event exactly once", () => {
  const stream = [
    event("session.status", { status: "planning" }),
    event("plan.proposed", { plan: { task: "t", rationale: "", steps: [] } }),
    event("tool.proposed", { action: { id: "a1", summary: "Read x", action_type: "file.read" } }),
  ];

  const live = fold(stream);
  // The server replays from seq 1 after a drop; the last two arrive twice.
  const withOverlap = fold([...stream.slice(1), ...stream.slice(1)], fold(stream.slice(0, 1)));

  assert.equal(withOverlap.lastSeq, live.lastSeq);
  assert.equal(withOverlap.chat.length, live.chat.length);
});

test("an approval is held until it resolves", () => {
  const action = { id: "act_1", summary: "Delete scratch.tmp", action_type: "file.delete" };
  let state = fold([
    event("approval.required", { action, decision: { requires_approval: true, reason: "r" } }),
  ]);
  assert.equal(state.pending?.action.id, "act_1");

  state = reduceEvent(state, event("approval.resolved", { approved: true, auto: false }));
  assert.equal(state.pending, null);
  assert.equal(state.chat.at(-1)?.text, "You approved this action");
});

test("auto-approvals clear the gate without narrating a decision nobody made", () => {
  const state = fold([
    event("tool.proposed", { action: { id: "a", summary: "Read x", action_type: "file.read" } }),
    event("approval.resolved", { approved: true, auto: true }),
  ]);
  assert.deepEqual(
    state.chat.map((item) => item.kind),
    ["proposal"],
  );
});

test("tool proposals carry where the command will run", () => {
  const state = fold([
    event("tool.proposed", {
      action: {
        id: "a",
        summary: "Run: pytest",
        action_type: "shell.test",
        preview: { runs_in: { kind: "container", isolated: true } },
      },
    }),
  ]);
  assert.equal(state.chat[0].runsIn, "container");
});

test("diffs are keyed by path so a file edited twice shows once", () => {
  const state = fold([
    event("diff.generated", { diff: { path: "a.py", hunks: [{ id: "h0" }] } }),
    event("diff.generated", { diff: { path: "a.py", hunks: [{ id: "h0" }, { id: "h1" }] } }),
    event("diff.generated", { diff: { path: "b.py", hunks: [] } }),
  ]);
  assert.deepEqual(Object.keys(state.diffs).sort(), ["a.py", "b.py"]);
  assert.equal(state.diffs["a.py"].hunks.length, 2);
});

test("plan steps update in place as they run", () => {
  const plan = {
    task: "t",
    rationale: "",
    steps: [
      { index: 0, description: "one", tool: "shell", params: {}, status: "pending" },
      { index: 1, description: "two", tool: "shell", params: {}, status: "pending" },
    ],
  };
  const state = fold([
    event("plan.proposed", { plan }),
    event("plan.step.started", { step: { ...plan.steps[0], status: "running" } }),
    event("plan.step.completed", { step: { ...plan.steps[0], status: "complete" } }),
  ]);

  assert.equal(state.currentStep, 0);
  assert.deepEqual(
    state.steps.map((step) => step.status),
    ["complete", "pending"],
  );
});

test("terminal events end the stream", () => {
  const complete = fold([event("session.complete", { status: "complete", elapsed_s: 1.5 })]);
  assert.equal(complete.ended, true);
  assert.equal(complete.status, "complete");

  const failed = fold([event("session.error", { status: "failed", error: "boom" })]);
  assert.equal(failed.ended, true);
  assert.equal(failed.status, "failed");
  assert.equal(failed.error, "boom");
});

test("a killed session is reported as terminated, not as success", () => {
  const state = fold([event("session.complete", { status: "killed", elapsed_s: 0.2 })]);
  assert.equal(state.chat.at(-1)?.text, "Session terminated");
  assert.equal(state.chat.at(-1)?.ok, false);
});

test("unknown event types are tolerated rather than throwing", () => {
  const state = fold([event("something.new" as any, { whatever: true })]);
  assert.equal(state.lastSeq, 1);
});

// ---- SessionStream ---------------------------------------------------------

class FakeSocket implements SocketLike {
  onopen: ((event: any) => void) | null = null;
  onclose: ((event: any) => void) | null = null;
  onerror: ((event: any) => void) | null = null;
  onmessage: ((event: { data: any }) => void) | null = null;
  closed = false;
  url: string;

  constructor(url: string) {
    this.url = url;
  }
  close(): void {
    this.closed = true;
    this.onclose?.({});
  }
  deliver(payload: SaniEvent): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

test("the stream reconnects from the last sequence it saw", async () => {
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream(
    "ws://x/session/s/stream",
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    1,
  );

  stream.connect();
  assert.match(sockets[0].url, /from_seq=0$/);

  sockets[0].onopen?.({});
  sockets[0].deliver(event("session.status", { status: "executing" }));
  sockets[0].deliver(event("plan.proposed", { plan: { task: "t", rationale: "", steps: [] } }));
  assert.equal(stream.getState().lastSeq, 2);

  sockets[0].close();
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(sockets.length, 2, "should have reconnected");
  assert.match(sockets[1].url, /from_seq=2$/);
  stream.dispose();
});

test("from_seq is appended with & when the url already has a query string", () => {
  // wsUrl() puts ?token=... on the base URL when auth is on. A bare
  // `?from_seq=` on top of that produces two `?` in one URL, which every
  // browser WebSocket constructor rejects outright -- and silently, from the
  // caller's perspective: connect() throws, so onopen/onmessage never fire
  // and the UI is stuck wherever the reducer's initial state left it.
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream(
    "ws://x/session/s/stream?token=secret",
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
  );

  stream.connect();

  assert.equal(sockets[0].url, "ws://x/session/s/stream?token=secret&from_seq=0");
  assert.equal((sockets[0].url.match(/\?/g) ?? []).length, 1);
  stream.dispose();
});

test("connect after dispose revives the stream (React StrictMode remount)", () => {
  // React runs effects mount -> cleanup -> mount in development. The adapter
  // memoises the stream per session id, so the *same* object gets disposed and
  // then reconnected. If dispose were permanent the second connect would be a
  // silent no-op and the session view would stay blank forever -- in dev only,
  // which is exactly where it hides longest.
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream("ws://x/session/s/stream", (url) => {
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket;
  });

  stream.connect();
  assert.equal(sockets.length, 1);

  stream.dispose();
  stream.connect();

  assert.equal(sockets.length, 2, "a disposed stream must reconnect on demand");
  stream.dispose();
});

test("dispose stops the reconnect timer rather than merely marking a flag", async () => {
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream(
    "ws://x/session/s/stream",
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    1,
  );

  stream.connect();
  stream.dispose();
  sockets[0].close();

  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(sockets.length, 1, "a disposed stream must not resurrect itself");
});

test("a finished session is not reconnected to", async () => {
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream(
    "ws://x/session/s/stream",
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    1,
  );

  stream.connect();
  sockets[0].deliver(event("session.complete", { status: "complete", elapsed_s: 1 }));
  sockets[0].close();
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(sockets.length, 1, "a completed session has nothing left to stream");
  stream.dispose();
});

test("subscribers are notified and a malformed frame does not kill the stream", () => {
  const sockets: FakeSocket[] = [];
  const stream = new SessionStream(
    "ws://x/session/s/stream",
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    1,
  );

  const seen: StreamState[] = [];
  stream.subscribe((state) => seen.push(state));
  stream.connect();

  sockets[0].onmessage?.({ data: "not json at all" });
  sockets[0].deliver(event("session.status", { status: "executing" }));

  assert.equal(seen.at(-1)?.status, "executing");
  assert.equal(sockets[0].closed, false);
  stream.dispose();
});

test("risk.assessed is held until the approval it describes arrives", () => {
  // The two events are separate frames but one moment. Rendering a score on its
  // own -- before the user knows what is being asked -- would be noise.
  const withRisk = reduceEvent(
    initialStreamState,
    event("risk.assessed", {
      action_id: "act_1",
      risk: { score: 80, band: "critical", factors: ["irreversible"] },
    }),
  );
  assert.equal(withRisk.pending, null, "a score alone is not a request");

  const withApproval = reduceEvent(
    withRisk,
    event("approval.required", {
      action: { id: "act_1", action_type: "file.delete", summary: "Delete x" },
      decision: { reason: "always-confirm" },
    }),
  );
  assert.equal(withApproval.pending?.risk?.score, 80);
  assert.equal(withApproval.pending?.risk?.band, "critical");
});

test("an approval with no assessment still renders", () => {
  // Older servers do not emit risk.assessed. The gate must not depend on it.
  const state = reduceEvent(
    initialStreamState,
    event("approval.required", {
      action: { id: "act_2", action_type: "file.delete", summary: "Delete y" },
      decision: { reason: "always-confirm" },
    }),
  );
  assert.ok(state.pending);
  assert.equal(state.pending?.risk, undefined);
});
