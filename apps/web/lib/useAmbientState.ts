"use client";

import { useEffect } from "react";

/**
 * Reactive state colour.
 *
 * The ambient layer breathes with session status -- it changes the temperature
 * of the room. It deliberately does NOT touch the three reserved channels
 * (agent violet, attention amber, risk red); those carry meaning and must stay
 * constant, or the semantic rule stops being reliable exactly when it matters.
 *
 * Writes CSS custom properties rather than React state so the shader and the
 * shell read the same source without a re-render per frame.
 */

export type SessionStatus =
  | "planning"
  | "executing"
  | "blocked-on-approval"
  | "paused"
  | "complete"
  | "failed"
  | "killed";

interface Ambient {
  /** 0-1. How present the field is. */
  intensity: number;
  /** Multiplier on the drift animation. */
  speed: number;
  /** Degrees added to the theme's base hue. Small: this is temperature, not
   *  repainting the theme. */
  shift: number;
}

const AMBIENT_BY_STATUS: Record<SessionStatus, Ambient> = {
  // Thinking: slow convection, slightly toward the agent channel.
  planning: { intensity: 0.5, speed: 0.7, shift: 6 },
  // Working: brighter and quicker, so peripheral vision registers activity.
  executing: { intensity: 0.62, speed: 1.35, shift: 0 },
  // The one state that must pull your eye. Warm, and it breathes.
  "blocked-on-approval": { intensity: 0.85, speed: 0.55, shift: 42 },
  paused: { intensity: 0.28, speed: 0.25, shift: 0 },
  complete: { intensity: 0.32, speed: 0.4, shift: -8 },
  // Failure blooms once and then sits as a dim ember rather than nagging.
  failed: { intensity: 0.55, speed: 0.5, shift: 96 },
  killed: { intensity: 0.18, speed: 0.2, shift: 0 },
};

const IDLE: Ambient = { intensity: 0.35, speed: 0.5, shift: 0 };

export function ambientFor(status: SessionStatus | null | undefined): Ambient {
  if (!status) return IDLE;
  return AMBIENT_BY_STATUS[status] ?? IDLE;
}

export function useAmbientState(status: SessionStatus | null | undefined): void {
  useEffect(() => {
    const { intensity, speed, shift } = ambientFor(status);
    const root = document.documentElement;
    root.style.setProperty("--ambient-intensity", intensity.toFixed(3));
    root.style.setProperty("--ambient-speed", speed.toFixed(3));
    root.style.setProperty("--ambient-shift", `${shift}`);
  }, [status]);
}
