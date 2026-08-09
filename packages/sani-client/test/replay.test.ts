import assert from "node:assert/strict";
import { test } from "node:test";
import {
  foldTo,
  keyframeAt,
  nextKeyframe,
  offsetOf,
  previousKeyframe,
  type Keyframe,
} from "../src/replay.ts";
import type { SaniEvent } from "../src/types.ts";

function event(seq: number, type: string, data: Record<string, unknown> = {}): SaniEvent {
  return { v: 1, seq, session_id: "ses_x", ts: seq, type, data } as SaniEvent;
}

const RUN: SaniEvent[] = [
  event(1, "session.status", { status: "planning" }),
  event(2, "plan.proposed", {
    plan: { task: "t", rationale: "r", steps: [{ description: "a", tool: "file_editor" }] },
  }),
  event(3, "session.status", { status: "executing" }),
  event(4, "diff.generated", {
    diff: { path: "greeting.py", hunks: [], additions: 2, deletions: 0 },
  }),
  event(5, "session.complete", { status: "complete", elapsed_s: 1.5 }),
];

const KEYFRAMES: Keyframe[] = [
  { seq: 2, kind: "plan", label: "Plan proposed — 1 step", ts: 2 },
  { seq: 4, kind: "diff", label: "Changed greeting.py", ts: 4 },
  { seq: 5, kind: "terminal", label: "Complete", ts: 5 },
];

test("folding to seq 0 is the session before anything happened", () => {
  const state = foldTo(RUN, 0);
  assert.equal(state.plan, null);
  assert.equal(state.ended, false);
  assert.deepEqual(state.diffs, {});
});

test("folding to a midpoint yields exactly the state at that moment", () => {
  const state = foldTo(RUN, 3);
  assert.equal(state.status, "executing");
  assert.ok(state.plan, "the plan had been proposed by seq 3");
  // The diff lands at seq 4, so scrubbing to 3 must not show it.
  assert.deepEqual(Object.keys(state.diffs), []);
});

test("folding to the end matches having watched the whole run live", () => {
  const replayed = foldTo(RUN, 5);
  const live = RUN.reduce(
    (state, next) => foldTo([...RUN.slice(0, RUN.indexOf(next) + 1)], next.seq),
    foldTo(RUN, 0),
  );
  assert.equal(replayed.status, live.status);
  assert.equal(replayed.ended, true);
  assert.deepEqual(Object.keys(replayed.diffs), ["greeting.py"]);
});

test("folding past the end is clamped by the log, not an error", () => {
  const state = foldTo(RUN, 9999);
  assert.equal(state.ended, true);
});

test("scrubbing backward and forward lands on identical state", () => {
  // The property that makes a scrubber trustworthy: position is a pure
  // function of seq, with no path dependence.
  const forward = foldTo(RUN, 4);
  const afterGoingFurther = foldTo(RUN, 5);
  const backAgain = foldTo(RUN, 4);
  assert.notDeepEqual(forward.status, undefined);
  assert.deepEqual(Object.keys(backAgain.diffs), Object.keys(forward.diffs));
  assert.equal(backAgain.ended, forward.ended);
  assert.equal(afterGoingFurther.ended, true);
});

test("keyframeAt reports the marker you are sitting on or just past", () => {
  assert.equal(keyframeAt(KEYFRAMES, 1), null);
  assert.equal(keyframeAt(KEYFRAMES, 2)?.seq, 2);
  assert.equal(keyframeAt(KEYFRAMES, 3)?.seq, 2);
  assert.equal(keyframeAt(KEYFRAMES, 4)?.seq, 4);
});

test("next and previous keyframe are strict, so repeated jumps advance", () => {
  assert.equal(nextKeyframe(KEYFRAMES, 2)?.seq, 4);
  assert.equal(nextKeyframe(KEYFRAMES, 5), null);
  assert.equal(previousKeyframe(KEYFRAMES, 4)?.seq, 2);
  assert.equal(previousKeyframe(KEYFRAMES, 2), null);
});

test("offsetOf measures from the first event, so playback keeps real rhythm", () => {
  assert.equal(offsetOf(RUN, 1), 0);
  assert.equal(offsetOf(RUN, 4), 3);
  assert.equal(offsetOf([], 5), 0);
});
