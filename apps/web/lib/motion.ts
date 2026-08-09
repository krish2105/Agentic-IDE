"use client";

import { useReducedMotion, type Transition, type Variants } from "motion/react";

/**
 * The motion vocabulary.
 *
 * Six primitives, applied consistently. No component hand-rolls a timing --
 * that is how a UI ends up feeling like six different products stitched
 * together. Every animation here either encodes state or directs attention;
 * decoration is not a category.
 *
 * Only `transform` and `opacity` are animated. Layout properties and
 * `backdrop-filter` are never animated on a scroll path.
 */

export const springs = {
  /** Default for panels and cards. Settles, does not bounce. */
  settle: { type: "spring", stiffness: 260, damping: 30, mass: 0.9 },
  /** Snappier, for controls responding to a direct click. */
  swift: { type: "spring", stiffness: 420, damping: 34, mass: 0.7 },
  /** Heavier, for large surfaces and shared-element morphs. */
  weighty: { type: "spring", stiffness: 180, damping: 28, mass: 1.1 },
  /** For values that should overshoot slightly then correct -- counters, dials. */
  overshoot: { type: "spring", stiffness: 500, damping: 18, mass: 0.6 },
} satisfies Record<string, Transition>;

/** Panels and cards entering. */
export const rise: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: springs.settle },
  exit: { opacity: 0, y: -8, transition: { duration: 0.15 } },
};

/** Scale-in for things that appear at a point rather than sliding in. */
export const bloom: Variants = {
  hidden: { opacity: 0, scale: 0.94 },
  visible: { opacity: 1, scale: 1, transition: springs.settle },
  exit: { opacity: 0, scale: 0.97, transition: { duration: 0.12 } },
};

/** Parent of a staggered list. 28ms reads as "cascading", not "slow". */
export const stagger: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.028, delayChildren: 0.04 } },
};

/** Child of a staggered list. */
export const staggerChild: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: springs.settle },
};

/** A value that just changed: brief overshoot, damped return. */
export const settle: Variants = {
  idle: { scale: 1 },
  changed: { scale: [1, 1.06, 1], transition: { duration: 0.34, times: [0, 0.4, 1] } },
};

/** The ONE looping animation in the product: something needs the human. */
export const attention: Variants = {
  idle: { opacity: 1 },
  pulsing: {
    opacity: [1, 0.55, 1],
    transition: { duration: 1.8, repeat: Infinity, ease: "easeInOut" },
  },
};

/** Inert equivalents used when the user asked for reduced motion. Positions
 *  resolve instantly; nothing translates, scales, or loops. */
const INERT: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.01 } },
  exit: { opacity: 0, transition: { duration: 0.01 } },
  idle: {},
  changed: {},
  pulsing: {},
};

/**
 * Returns the requested variants, or inert ones under reduced motion.
 *
 * Components call this instead of importing variants directly so the
 * reduced-motion contract cannot be forgotten at a call site.
 */
export function useGatedMotion(variants: Variants): Variants {
  const reduced = useReducedMotion();
  return reduced ? INERT : variants;
}

/** True when motion should be suppressed. For imperative cases (canvas loops,
 *  autoplay) that cannot express themselves as variants. */
export function useMotionAllowed(): boolean {
  return !useReducedMotion();
}
