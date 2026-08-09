"use client";

import type { Keyframe } from "@sani/client";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useMemo, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { springs } from "@/lib/motion";
import { SPEEDS, type Replay } from "@/lib/useReplay";

/**
 * The replay scrubber.
 *
 * A finished agent session is a recording nobody can watch. This is the tape
 * head: drag through the run and the whole IDE -- chat, plan, diffs, file
 * tree -- reconstructs itself at that instant, because the reducer that folds
 * live events is the same one folding history.
 */

const KEYFRAME_STYLE: Record<Keyframe["kind"], { color: string; title: string }> = {
  plan: { color: "bg-ink-faint", title: "Plan proposed" },
  approval: { color: "bg-attention", title: "Stopped for you" },
  diff: { color: "bg-agent", title: "File changed" },
  failure: { color: "bg-danger", title: "Failure" },
  terminal: { color: "bg-ok", title: "Session ended" },
};

export function ReplayScrubber({ replay }: { replay: Replay }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const { timeline, seq, playing, speed, marker } = replay;

  const last = timeline?.last_seq ?? 0;
  const progress = last > 0 && seq !== null ? Math.min(seq / last, 1) : 0;

  const seekFromPointer = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track || last <= 0) return;
      const rect = track.getBoundingClientRect();
      const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
      replay.scrubTo(Math.round(ratio * last));
    },
    [last, replay],
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Capture keeps the drag alive when the pointer leaves the track, but a
      // synthetic or already-released pointer id throws -- and an exception here
      // would take the seek down with it. The drag is the enhancement; landing
      // on the clicked position is the part that must not fail.
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* no capture available; click-to-seek still works */
      }
      seekFromPointer(event.clientX);
    },
    [seekFromPointer],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.buttons !== 1) return;
      seekFromPointer(event.clientX);
    },
    [seekFromPointer],
  );

  const keyframes = useMemo(() => timeline?.keyframes ?? [], [timeline]);

  if (!replay.active) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: 56, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 56, opacity: 0 }}
        transition={springs.settle}
        className="glass-elevated flex shrink-0 items-center gap-3 border-t border-edge px-3 py-2"
        data-testid="replay-scrubber"
      >
        <span className="shrink-0 rounded-md bg-agent/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-agent">
          Replay
        </span>

        <div className="flex shrink-0 items-center gap-0.5">
          <Button size="sm" variant="ghost" onClick={replay.jumpPrev} title="Previous keyframe">
            ⏮
          </Button>
          <Button size="sm" variant="ghost" onClick={replay.stepBack} title="Step back">
            ◀
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={playing ? replay.pause : replay.play}
            title={playing ? "Pause" : "Play"}
            data-testid="replay-play"
          >
            {playing ? "❚❚" : "▶"}
          </Button>
          <Button size="sm" variant="ghost" onClick={replay.stepForward} title="Step forward">
            ▶
          </Button>
          <Button size="sm" variant="ghost" onClick={replay.jumpNext} title="Next keyframe">
            ⏭
          </Button>
        </div>

        {/* The track. Keyframes are the point: the eye finds the amber marks
            (moments that stopped for a human) before it reads anything. */}
        <div
          ref={trackRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          role="slider"
          tabIndex={0}
          data-testid="replay-track"
          aria-label="Replay position"
          aria-valuemin={0}
          aria-valuemax={last}
          aria-valuenow={seq ?? 0}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") replay.stepBack();
            if (event.key === "ArrowRight") replay.stepForward();
            if (event.key === " ") {
              event.preventDefault();
              playing ? replay.pause() : replay.play();
            }
          }}
          className="relative h-8 min-w-0 flex-1 cursor-pointer touch-none rounded-md"
        >
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-edge" />
          <motion.div
            className="absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-agent"
            style={{ width: `${progress * 100}%` }}
            layout
            transition={springs.swift}
          />

          {keyframes.map((frame) => {
            const style = KEYFRAME_STYLE[frame.kind];
            return (
              <button
                key={`${frame.kind}-${frame.seq}`}
                onClick={(event) => {
                  event.stopPropagation();
                  replay.scrubTo(frame.seq);
                }}
                title={`${style.title} — ${frame.label}`}
                aria-label={frame.label}
                data-testid="replay-keyframe"
                data-kind={frame.kind}
                style={{ left: `${last > 0 ? (frame.seq / last) * 100 : 0}%` }}
                className={`absolute top-1/2 h-2.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ${style.color} transition-transform hover:scale-y-150`}
              />
            );
          })}

          <motion.div
            className="pointer-events-none absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-agent bg-base shadow-lg"
            style={{ left: `${progress * 100}%` }}
            layout
            transition={springs.swift}
          />
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {SPEEDS.map((option) => (
            <button
              key={option}
              onClick={() => replay.setSpeed(option)}
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
                speed === option
                  ? "bg-raised text-ink"
                  : "text-ink-faint hover:text-ink-dim"
              }`}
            >
              {option}×
            </button>
          ))}
        </div>

        <span
          className="hidden min-w-0 max-w-[18rem] shrink truncate font-mono text-[10px] text-ink-faint lg:block"
          title={marker?.label}
        >
          {marker?.label ?? "start of session"}
        </span>

        <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-dim">
          {seq ?? 0}/{last}
        </span>

        <Button size="sm" variant="ghost" onClick={replay.exit} data-testid="replay-exit">
          Live
        </Button>
      </motion.div>
    </AnimatePresence>
  );
}
