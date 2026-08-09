"use client";

import type { Critique, CritiqueVerdict } from "@sani/client";
import { motion } from "motion/react";
import { springs } from "@/lib/motion";

/**
 * The second opinion, shown beside the request it reviewed.
 *
 * Deliberately quiet when it has nothing to say. A critic that announces
 * "looks fine" on every screen trains you to stop reading it, and then it is
 * worth nothing on the one screen where it mattered.
 *
 * It is also never styled to look like a decision. The buttons below it are the
 * decision; this is evidence.
 */

const VERDICT: Record<CritiqueVerdict, { label: string; tone: string }> = {
  "looks-right": { label: "No concerns", tone: "text-ink-faint" },
  concerns: { label: "Worth a look", tone: "text-attention" },
  "likely-wrong": { label: "Likely wrong", tone: "text-risk" },
};

export function CritiqueNote({ critique }: { critique: Critique }) {
  // A critic that failed is reported rather than hidden -- silence would read
  // as "reviewed and fine".
  if (critique.error) {
    return (
      <p className="rounded-lg border border-edge bg-base/40 px-2.5 py-1.5 text-[10px] text-ink-faint">
        Second opinion unavailable — the critic errored. This action was
        <span className="text-ink-dim"> not </span>reviewed.
      </p>
    );
  }

  // Nothing to say, and no reviewer configured: stay out of the way entirely.
  if (critique.clean && !critique.reviewed_by) return null;

  const style = VERDICT[critique.verdict];

  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springs.settle}
      className="rounded-lg border border-edge bg-base/40 p-2.5"
    >
      <div className="flex items-baseline gap-2">
        <span className={`text-[11px] font-semibold ${style.tone}`}>{style.label}</span>
        <span className="font-mono text-[10px] text-ink-faint">
          second opinion · {critique.reviewed_by}
        </span>
      </div>

      {critique.concerns.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {critique.concerns.map((concern) => (
            <li key={concern} className="flex gap-2 text-[11px] leading-snug text-ink-dim">
              <span className="text-ink-faint" aria-hidden>
                ·
              </span>
              <span>{concern}</span>
            </li>
          ))}
        </ul>
      )}
    </motion.div>
  );
}
