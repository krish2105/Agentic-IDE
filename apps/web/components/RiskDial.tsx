"use client";

import type { RiskAssessment, RiskBand } from "@sani/client";
import { motion } from "motion/react";
import { useState } from "react";
import { springs, useMotionAllowed } from "@/lib/motion";

/**
 * Blast radius, shown before the decision.
 *
 * The score is the summary; the factors are the feature. A bare number is
 * something to click past, which is the exact failure this is meant to prevent
 * -- so the reasoning is one click away and the irreversibility is stated in
 * words, not implied by a colour.
 */

const BAND_STYLE: Record<RiskBand, { text: string; ring: string; label: string }> = {
  low: { text: "text-ok", ring: "stroke-ok", label: "Low" },
  medium: { text: "text-attention", ring: "stroke-attention", label: "Medium" },
  high: { text: "text-risk", ring: "stroke-risk", label: "High" },
  critical: { text: "text-risk", ring: "stroke-risk", label: "Critical" },
};

export function RiskDial({ risk }: { risk: RiskAssessment }) {
  const [open, setOpen] = useState(false);
  const animated = useMotionAllowed();
  const style = BAND_STYLE[risk.band];

  const radius = 15;
  const circumference = 2 * Math.PI * radius;
  const filled = (risk.score / 100) * circumference;

  return (
    <div
      className="rounded-lg border border-edge bg-base/40 p-2.5"
      data-testid="risk-dial"
      data-band={risk.band}
      data-score={risk.score}
      data-reversible={risk.reversible}
    >
      <div className="flex items-start gap-3">
        <svg viewBox="0 0 36 36" className="h-11 w-11 shrink-0 -rotate-90" aria-hidden>
          <circle
            cx="18"
            cy="18"
            r={radius}
            fill="none"
            strokeWidth="3"
            className="stroke-edge"
          />
          <motion.circle
            cx="18"
            cy="18"
            r={radius}
            fill="none"
            strokeWidth="3"
            strokeLinecap="round"
            className={style.ring}
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: animated ? circumference : circumference - filled }}
            animate={{ strokeDashoffset: circumference - filled }}
            transition={springs.settle}
          />
        </svg>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className={`text-sm font-semibold ${style.text}`}>{style.label} risk</span>
            <span className="font-mono text-[10px] tabular-nums text-ink-faint">
              {risk.score}/100
            </span>
          </div>

          <p className="mt-0.5 text-[11px] leading-snug text-ink-dim">
            {risk.reversible
              ? "Reversible — the previous state can be recovered."
              : "Cannot be undone from inside Ṣāni'."}
            {risk.lines_changed > 0 &&
              ` ${risk.lines_changed} line${risk.lines_changed === 1 ? "" : "s"} change${
                risk.lines_changed === 1 ? "s" : ""
              }.`}
          </p>

          <button
            onClick={() => setOpen((value) => !value)}
            className="mt-1 text-[10px] uppercase tracking-wider text-ink-faint transition-colors hover:text-ink-dim"
            aria-expanded={open}
            data-testid="risk-why"
          >
            {open ? "Hide reasoning" : `Why — ${risk.factors.length} factor${risk.factors.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>

      {open && (
        <motion.ul
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="mt-2 space-y-1 border-t border-edge pt-2"
          data-testid="risk-factors"
        >
          {risk.factors.map((factor) => (
            <li key={factor} className="flex gap-2 text-[11px] leading-snug text-ink-dim">
              <span className="text-ink-faint" aria-hidden>
                ·
              </span>
              <span>{factor}</span>
            </li>
          ))}
        </motion.ul>
      )}
    </div>
  );
}
