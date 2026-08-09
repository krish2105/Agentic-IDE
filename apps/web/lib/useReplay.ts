"use client";

import {
  foldTo,
  keyframeAt,
  nextKeyframe,
  previousKeyframe,
  type Keyframe,
  type StreamState,
  type Timeline,
} from "@sani/client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./client";

export const SPEEDS = [1, 2, 4, 8] as const;
export type Speed = (typeof SPEEDS)[number];

export interface Replay {
  available: boolean;
  loading: boolean;
  error: string | null;
  timeline: Timeline | null;
  /** Where the scrubber is. Null means "follow live", not "at zero". */
  seq: number | null;
  active: boolean;
  playing: boolean;
  speed: Speed;
  /** Session state folded to `seq`, or null when following live. */
  state: StreamState | null;
  marker: Keyframe | null;
  enter: () => void;
  exit: () => void;
  scrubTo: (seq: number) => void;
  play: () => void;
  pause: () => void;
  setSpeed: (speed: Speed) => void;
  stepBack: () => void;
  stepForward: () => void;
  jumpPrev: () => void;
  jumpNext: () => void;
}

/**
 * Replay for one session.
 *
 * Loads the log once on entering replay, then scrubs entirely client-side --
 * the fold is cheap and re-fetching per frame would make dragging feel awful.
 *
 * Playback advances on the log's own timestamps rather than a fixed tick, so a
 * replay has the rhythm the run actually had: the ninety seconds a human spent
 * deciding shows up as ninety seconds of stillness, which is exactly the thing
 * a reviewer wants to notice.
 */
export function useReplay(sessionId: string, liveEnded: boolean): Replay {
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seq, setSeq] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(2);

  const active = seq !== null;
  const raf = useRef<number | null>(null);
  const lastTick = useRef<number>(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTimeline(await api.timeline(sessionId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const enter = useCallback(() => {
    void load().then(() => setSeq(0));
  }, [load]);

  const exit = useCallback(() => {
    setPlaying(false);
    setSeq(null);
  }, []);

  const scrubTo = useCallback((next: number) => {
    setPlaying(false);
    setSeq(Math.max(0, next));
  }, []);

  // Playback. Driven by real elapsed time against the log's timestamps.
  useEffect(() => {
    if (!playing || !timeline || seq === null) return;

    const events = timeline.events;
    if (events.length === 0) return;

    lastTick.current = performance.now();

    const step = (now: number) => {
      const deltaS = ((now - lastTick.current) / 1000) * speed;
      lastTick.current = now;

      setSeq((current) => {
        if (current === null) return current;
        const at = events.find((event) => event.seq > current);
        if (!at) {
          setPlaying(false);
          return current;
        }
        // Advance through every event whose timestamp falls inside this frame's
        // slice of session-time, so fast speeds skip rather than stutter.
        let cursor = current;
        let budget = deltaS;
        let previousTs = events.find((event) => event.seq === current)?.ts ?? at.ts;
        for (const event of events) {
          if (event.seq <= cursor) continue;
          const gap = Math.max(0, event.ts - previousTs);
          if (gap > budget) break;
          budget -= gap;
          previousTs = event.ts;
          cursor = event.seq;
        }
        // A long real pause would otherwise freeze the scrubber entirely;
        // always make at least one event of progress per frame.
        return cursor === current ? at.seq : cursor;
      });

      raf.current = requestAnimationFrame(step);
    };

    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [playing, timeline, speed, seq === null]);

  const state = useMemo(() => {
    if (seq === null || !timeline) return null;
    return foldTo(timeline.events, seq);
  }, [timeline, seq]);

  const marker = useMemo(() => {
    if (seq === null || !timeline) return null;
    return keyframeAt(timeline.keyframes, seq);
  }, [timeline, seq]);

  const jumpPrev = useCallback(() => {
    if (!timeline || seq === null) return;
    scrubTo(previousKeyframe(timeline.keyframes, seq)?.seq ?? 0);
  }, [timeline, seq, scrubTo]);

  const jumpNext = useCallback(() => {
    if (!timeline || seq === null) return;
    const next = nextKeyframe(timeline.keyframes, seq);
    if (next) scrubTo(next.seq);
  }, [timeline, seq, scrubTo]);

  const stepBack = useCallback(() => {
    if (seq === null) return;
    scrubTo(seq - 1);
  }, [seq, scrubTo]);

  const stepForward = useCallback(() => {
    if (seq === null || !timeline) return;
    scrubTo(Math.min(seq + 1, timeline.last_seq));
  }, [seq, timeline, scrubTo]);

  return {
    // Replay is offered for any session with a log, but it is the natural
    // thing to reach for once a run has ended.
    available: liveEnded || timeline !== null,
    loading,
    error,
    timeline,
    seq,
    active,
    playing,
    speed,
    state,
    marker,
    enter,
    exit,
    scrubTo,
    play: () => setPlaying(true),
    pause: () => setPlaying(false),
    setSpeed,
    stepBack,
    stepForward,
    jumpPrev,
    jumpNext,
  };
}
