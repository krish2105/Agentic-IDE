/**
 * Replay: reconstruct session state at any point in its history.
 *
 * This deliberately reuses `reduceEvent` rather than reimplementing the fold.
 * The reducer is the single definition of what a session *is*; a replay that
 * folded events its own way would be a second definition, free to drift, and
 * the bug would surface as "the scrubber disagrees with the live view" -- the
 * hardest kind to chase.
 *
 * The log is gapless and monotonic by protocol invariant, so folding a prefix
 * is exactly what the client would have held had it been watching live.
 */

import { initialStreamState, reduceEvent, type StreamState } from "./stream.ts";
import type { SaniEvent } from "./types.ts";

export type KeyframeKind = "plan" | "approval" | "diff" | "failure" | "terminal";

export interface Keyframe {
  seq: number;
  kind: KeyframeKind;
  label: string;
  ts: number;
}

export interface Timeline {
  session_id: string;
  first_seq: number;
  last_seq: number;
  from_seq: number;
  count: number;
  duration_s: number;
  complete: boolean;
  keyframes: Keyframe[];
  events: SaniEvent[];
}

/**
 * Fold the log up to and including `seq`.
 *
 * `seq <= 0` yields the pristine initial state, which is what the scrubber
 * shows at position zero: the session as it was before anything happened.
 */
export function foldTo(events: SaniEvent[], seq: number): StreamState {
  let state = initialStreamState;
  if (seq <= 0) return state;

  for (const event of events) {
    if (event.seq > seq) break;
    state = reduceEvent(state, event);
  }
  return state;
}

/**
 * The nearest keyframe at or before `seq`.
 *
 * Used to label the scrubber's current position: while dragging, "you are just
 * after the approval on greeting.py" is far more useful than "event 47".
 */
export function keyframeAt(keyframes: Keyframe[], seq: number): Keyframe | null {
  let found: Keyframe | null = null;
  for (const frame of keyframes) {
    if (frame.seq > seq) break;
    found = frame;
  }
  return found;
}

/** The next keyframe strictly after `seq`, for jump-to-next. */
export function nextKeyframe(keyframes: Keyframe[], seq: number): Keyframe | null {
  return keyframes.find((frame) => frame.seq > seq) ?? null;
}

/** The previous keyframe strictly before `seq`, for jump-to-previous. */
export function previousKeyframe(keyframes: Keyframe[], seq: number): Keyframe | null {
  let found: Keyframe | null = null;
  for (const frame of keyframes) {
    if (frame.seq >= seq) break;
    found = frame;
  }
  return found;
}

/**
 * Wall-clock offset of an event, in seconds from the start of the run.
 *
 * Playback is driven by the log's own timestamps rather than a fixed tick, so
 * a replay has the rhythm the session actually had -- the long pause while a
 * human decided is visible as a pause.
 */
export function offsetOf(events: SaniEvent[], seq: number): number {
  if (events.length === 0) return 0;
  const start = events[0].ts;
  const target = events.find((event) => event.seq >= seq) ?? events[events.length - 1];
  return Math.max(0, target.ts - start);
}
