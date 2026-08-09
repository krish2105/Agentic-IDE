"use client";

import { motion, type HTMLMotionProps } from "motion/react";
import { rise, useGatedMotion } from "@/lib/motion";

type Elevation = 0 | 1 | 2 | 3;

interface GlassPanelProps extends Omit<HTMLMotionProps<"div">, "variants"> {
  /**
   * 0 — flat, no border (structural containers)
   * 1 — hairline border, opaque-ish (docks, trees, lists)
   * 2 — blurred glass (nav, popovers)          ← backdrop-filter starts here
   * 3 — blurred glass + lift (modals, approval cards)
   *
   * `backdrop-filter` costs 15-30% FPS on mid-tier hardware, so elevations 0-1
   * deliberately do without it. Scrolling regions must stay at 0-1.
   */
  elevation?: Elevation;
  animate?: boolean;
}

const ELEVATION_CLASS: Record<Elevation, string> = {
  0: "bg-surface",
  1: "bg-surface/85 border border-edge",
  2: "glass-elevated rounded-xl",
  3: "glass-elevated rounded-2xl shadow-[0_24px_70px_-20px_rgba(0,0,0,0.75)]",
};

export function GlassPanel({
  elevation = 1,
  animate = false,
  className = "",
  children,
  ...rest
}: GlassPanelProps) {
  const variants = useGatedMotion(rise);

  return (
    <motion.div
      className={`${ELEVATION_CLASS[elevation]} ${className}`}
      variants={animate ? variants : undefined}
      initial={animate ? "hidden" : undefined}
      animate={animate ? "visible" : undefined}
      exit={animate ? "exit" : undefined}
      {...rest}
    >
      {children}
    </motion.div>
  );
}
