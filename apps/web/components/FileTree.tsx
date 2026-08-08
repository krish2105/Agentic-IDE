"use client";

import { useMemo } from "react";
import type { FileEntry } from "@sani/client";

interface Props {
  entries: FileEntry[];
  activePath: string | null;
  agentTouchedPaths: Set<string>;
  onOpen: (path: string) => void;
  onRefresh: () => void;
  loading: boolean;
}

function depthOf(path: string): number {
  return path.split("/").length - 1;
}

export function FileTree({
  entries,
  activePath,
  agentTouchedPaths,
  onOpen,
  onRefresh,
  loading,
}: Props) {
  const rows = useMemo(
    () => entries.map((entry) => ({ ...entry, depth: depthOf(entry.path) })),
    [entries],
  );

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-edge bg-surface">
      <div className="flex h-8 items-center justify-between border-b border-edge px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
          Explorer
        </span>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-[11px] text-ink-faint hover:text-ink disabled:opacity-40"
          title="Refresh file tree"
        >
          {loading ? "…" : "↻"}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-1" data-testid="file-tree">
        {rows.length === 0 && (
          <p className="px-3 py-2 text-xs text-ink-faint">Empty workspace</p>
        )}
        {rows.map((entry) => {
          const touched = agentTouchedPaths.has(entry.path);
          const active = entry.path === activePath;
          return (
            <button
              key={entry.path}
              onClick={() => entry.type === "file" && onOpen(entry.path)}
              data-testid={`file-${entry.path}`}
              data-agent-touched={touched}
              className={`flex w-full items-center gap-1.5 truncate py-[3px] pr-2 text-left text-xs ${
                active ? "bg-raised text-ink" : "text-ink-dim hover:bg-raised/60 hover:text-ink"
              } ${entry.type === "dir" ? "cursor-default" : "cursor-pointer"}`}
              style={{ paddingLeft: `${10 + entry.depth * 12}px` }}
            >
              <span className="w-3 shrink-0 text-center text-ink-faint">
                {entry.type === "dir" ? "▸" : "·"}
              </span>
              <span className={`truncate font-mono ${touched ? "text-agent" : ""}`}>
                {entry.name}
              </span>
              {touched && (
                <span
                  className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-agent"
                  title="Modified by the agent"
                />
              )}
            </button>
          );
        })}
      </div>
    </aside>
  );
}
