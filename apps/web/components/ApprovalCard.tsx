"use client";

import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { springs } from "@/lib/motion";
import type { PendingApproval } from "@/lib/useSessionStream";
import { DiffView } from "./DiffView";
import { CritiqueNote } from "./CritiqueNote";
import { RiskDial } from "./RiskDial";

interface Props {
  pending: PendingApproval;
  onApprove: (hunkIds: string[] | null) => void;
  onReject: () => void;
  busy: boolean;
}

/**
 * The approval card.
 *
 * This is the surface the entire product exists to render well. Everything
 * else is instrumentation; this is the moment a human is asked to take
 * responsibility for something irreversible, and it has to make the stakes
 * legible in about two seconds.
 *
 * Structure, in the order the eye should travel:
 *   1. what is being asked, and why it stopped
 *   2. what will actually happen (command, diff, where it runs)
 *   3. what rejecting costs
 *   4. the decision
 */
export function ApprovalCard({ pending, onApprove, onReject, busy }: Props) {
  const { action, decision } = pending;
  const hunks = action.diff?.hunks ?? [];
  const runsIn = (action.preview as Record<string, any> | undefined)?.runs_in;

  // Default to accepting everything: the common case is "yes, do it", and
  // making the user re-tick every hunk to get there would train them to click
  // through without reading, which is the failure this whole gate exists to
  // prevent.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    setSelected(new Set(hunks.map((hunk) => hunk.id)));
  }, [action.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allSelected = hunks.length > 0 && selected.size === hunks.length;
  const partial = hunks.length > 0 && !allSelected;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={springs.settle}
      data-testid="approval-card"
      data-action-type={action.action_type}
      className="glass-elevated relative overflow-hidden rounded-xl border-attention/40"
    >
      {/* Amber edge light. The card should feel lit from within rather than
          outlined -- an outline reads as a warning box, and this is a request. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-attention to-transparent" />
      <div className="pointer-events-none absolute inset-0 bg-attention/[0.04]" />

      <div className="relative p-3.5">
        <div className="mb-2.5 flex items-center gap-2">
          <span className="pulse-attention h-1.5 w-1.5 rounded-full bg-attention" />
          <span className="text-xs font-semibold tracking-tight text-attention">
            Waiting on you
          </span>
          <code className="ml-auto rounded-md bg-base/60 px-1.5 py-0.5 font-mono text-[10px] text-ink-dim">
            {action.action_type}
          </code>
        </div>

        <p className="mb-1.5 text-sm leading-snug text-ink" data-testid="approval-summary">
          {action.summary}
        </p>
        <p className="mb-3 text-[11px] leading-relaxed text-ink-faint">{decision.reason}</p>

        {/* Blast radius, before the decision rather than after it. Absent when
            talking to a server that predates risk assessment. */}
        {(pending.risk || pending.critique) && (
          <div className="mb-3 space-y-2">
            {pending.risk && <RiskDial risk={pending.risk} />}
            {pending.critique && <CritiqueNote critique={pending.critique} />}
          </div>
        )}

        {action.preview?.command && (
          <div className="mb-3">
            <div className="mb-1 flex items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                Command
              </span>
              {/* Where a command lands is part of the decision, not a detail:
                  "host" and "container" are different risks entirely. */}
              {runsIn && (
                <span
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                    runsIn.isolated
                      ? "bg-ok/15 text-ok"
                      : "bg-attention/15 text-attention"
                  }`}
                  title={
                    runsIn.isolated
                      ? "Runs inside the session sandbox"
                      : "Runs directly on this machine, as the server user"
                  }
                >
                  {runsIn.isolated ? "sandboxed" : "on host"}
                </span>
              )}
            </div>
            <pre className="overflow-x-auto rounded-lg border border-edge bg-base/70 px-3 py-2 font-mono text-[11px] text-ink">
              $ {action.preview.command}
            </pre>
          </div>
        )}

        {action.diff && hunks.length > 0 && (
          <div className="mb-3">
            <DiffView diff={action.diff} selectedHunks={selected} onToggleHunk={toggle} />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="attention"
            size="sm"
            onClick={() => onApprove(partial ? Array.from(selected) : null)}
            disabled={busy}
            data-testid="approve-button"
          >
            {partial ? `Approve ${selected.size} of ${hunks.length}` : "Approve"}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={onReject}
            disabled={busy}
            data-testid="reject-button"
          >
            Reject
          </Button>

          {/* What rejecting costs. Without this the safe-looking button is the
              one whose consequences are least visible. */}
          <span className="text-[10px] leading-tight text-ink-faint">
            Rejecting skips this step; the plan continues.
          </span>

          <span className="ml-auto font-mono text-[10px] text-ink-faint">{action.id}</span>
        </div>
      </div>
    </motion.div>
  );
}
