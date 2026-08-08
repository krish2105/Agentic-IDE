"use client";

import type { FileDiff, Hunk } from "@sani/client";

/**
 * Added lines carry the agent accent, per spec Section 6: agent-authored lines
 * are marked before you decide about them, not after.
 */
function HunkLines({ hunk }: { hunk: Hunk }) {
  return (
    <pre className="overflow-x-auto font-mono text-[11px] leading-[1.6]">
      {hunk.lines.map((line, index) => {
        const marker = line[0];
        const added = marker === "+";
        const removed = marker === "-";
        return (
          <div
            key={index}
            className={`whitespace-pre px-3 ${
              added
                ? "agent-line bg-agent/10 text-ink"
                : removed
                  ? "border-l-2 border-danger/60 bg-danger/5 text-ink-dim"
                  : "border-l-2 border-transparent text-ink-faint"
            }`}
          >
            {line.replace(/\n$/, "") || " "}
          </div>
        );
      })}
    </pre>
  );
}

interface Props {
  diff: FileDiff;
  /** When provided, each hunk gets a checkbox for per-hunk accept. */
  selectedHunks?: Set<string>;
  onToggleHunk?: (hunkId: string) => void;
}

export function DiffView({ diff, selectedHunks, onToggleHunk }: Props) {
  const selectable = Boolean(selectedHunks && onToggleHunk);

  return (
    <div className="overflow-hidden rounded-md border border-edge bg-surface">
      <div className="flex items-center gap-2 border-b border-edge px-3 py-2">
        <span className="font-mono text-xs text-ink" data-testid={`diff-path-${diff.path}`}>
          {diff.path}
        </span>
        {diff.is_new_file && (
          <span className="rounded bg-ok/15 px-1.5 py-0.5 text-[10px] text-ok">new file</span>
        )}
        {diff.is_delete && (
          <span className="rounded bg-danger/15 px-1.5 py-0.5 text-[10px] text-danger">
            deleted
          </span>
        )}
        <span className="ml-auto text-[11px] text-ink-faint">
          {diff.hunks.length} hunk{diff.hunks.length === 1 ? "" : "s"}
        </span>
      </div>

      {diff.hunks.map((hunk) => {
        const checked = selectedHunks?.has(hunk.id) ?? false;
        return (
          <div key={hunk.id} className="border-b border-edge last:border-b-0">
            <div className="flex items-center gap-2 bg-raised/60 px-3 py-1">
              {selectable && (
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggleHunk?.(hunk.id)}
                  data-testid={`hunk-toggle-${hunk.id}`}
                  className="h-3 w-3 accent-[#a78bfa]"
                  aria-label={`Include hunk ${hunk.id}`}
                />
              )}
              <span className="font-mono text-[10px] text-ink-faint">{hunk.header}</span>
              {selectable && !checked && (
                <span className="text-[10px] text-attention">will be skipped</span>
              )}
            </div>
            <HunkLines hunk={hunk} />
          </div>
        );
      })}
    </div>
  );
}
