"use client";

import { motion, type HTMLMotionProps } from "motion/react";
import { springs, useMotionAllowed } from "@/lib/motion";

type Variant = "primary" | "ghost" | "outline" | "danger" | "attention";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  variant?: Variant;
  size?: Size;
  children?: React.ReactNode;
}

/*
 * `attention` is the only variant permitted to use the amber channel, and
 * `danger`/`risk` the only ones permitted red. `primary` deliberately does NOT
 * use agent violet: violet marks agent-authored content, not "the button you
 * probably want". Blurring those two would break the whole semantic system.
 */
const VARIANT: Record<Variant, string> = {
  primary:
    "bg-ink text-base hover:bg-ink/90 disabled:bg-edge-strong disabled:text-ink-faint",
  ghost:
    "bg-transparent text-ink-dim hover:bg-raised hover:text-ink disabled:text-ink-faint",
  outline:
    "bg-transparent text-ink border border-edge-strong hover:bg-raised hover:border-ink-faint disabled:text-ink-faint",
  danger:
    "bg-transparent text-danger border border-danger/40 hover:bg-danger/10 hover:border-danger",
  attention:
    "bg-attention text-base font-medium hover:brightness-110 disabled:bg-edge-strong disabled:text-ink-faint",
};

const SIZE: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-sm gap-2 rounded-lg",
  lg: "h-11 px-5 text-sm gap-2 rounded-lg",
};

export function Button({
  variant = "ghost",
  size = "md",
  className = "",
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const animated = useMotionAllowed();

  return (
    <motion.button
      type="button"
      disabled={disabled}
      whileHover={animated && !disabled ? { y: -1 } : undefined}
      whileTap={animated && !disabled ? { scale: 0.97 } : undefined}
      transition={springs.swift}
      className={[
        "inline-flex items-center justify-center font-medium",
        "transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-60",
        SIZE[size],
        VARIANT[variant],
        className,
      ].join(" ")}
      {...rest}
    >
      {children}
    </motion.button>
  );
}
