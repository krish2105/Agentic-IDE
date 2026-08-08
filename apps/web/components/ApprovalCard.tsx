"use client";

import { useEffect, useState } from "react";
import type { PendingApproval } from "@/lib/useSessionStream";
import { DiffView } from "./DiffView";

interface Props {
  pending: PendingApproval;
  onApprove: (hunkIds: string[] | null) => void;
  onReject: () => void;
  busy: boolean;
}

export function ApprovalCard({ pending, onApprove, onReject, busy }: Props) {
  const { action, decision } = pending;
  const hunks = action.diff?.hunks ?? [];

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
    <div
      data-testid="approval-card"
      data-action-type={action.action_type}
      className="rounded-md border border-attention/50 bg-attention/[0.06] p-3"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-attention pulse-attention" />
        <span className="text-xs font-semibold text-attention">Approval required</span>
        <code className="ml-auto rounded bg-raised px-1.5 py-0.5 font-mono text-[10px] text-ink-dim">
          {action.action_type}
        </code>
      </div>

      <p className="mb-1 text-sm text-ink" data-testid="approval-summary">
        {action.summary}
      </p>
      <p className="mb-3 text-[11px] text-ink-faint">{decision.reason}</p>

      {action.preview?.command && (
        <pre className="mb-3 overflow-x-auto rounded border border-edge bg-base px-3 py-2 font-mono text-[11px] text-ink">
          $ {action.preview.command}
        </pre>
      )}

      {action.diff && hunks.length > 0 && (
        <div className="mb-3">
          <DiffView diff={action.diff} selectedHunks={selected} onToggleHunk={toggle} />
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={() => onApprove(partial ? Array.from(selected) : null)}
          disabled={busy}
          data-testid="approve-button"
          className="rounded bg-ok/20 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/30 disabled:opacity-40"
        >
          {partial ? `Approve ${selected.size} of ${hunks.length} hunks` : "Approve"}
        </button>
        <button
          onClick={onReject}
          disabled={busy}
          data-testid="reject-button"
          className="rounded border border-edge px-3 py-1.5 text-xs text-ink-dim hover:border-danger hover:text-danger disabled:opacity-40"
        >
          Reject
        </button>
        <span className="ml-auto font-mono text-[10px] text-ink-faint">{action.id}</span>
      </div>
    </div>
  );
}
