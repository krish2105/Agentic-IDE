"use client";

import Link from "next/link";
import type { MissionControlRow, SessionStatus } from "@sani/client";

const DOT: Record<SessionStatus, string> = {
  planning: "bg-ink-faint",
  executing: "bg-ok",
  "blocked-on-approval": "bg-attention",
  paused: "bg-ink-faint",
  complete: "bg-ok/50",
  failed: "bg-danger",
  killed: "bg-danger/60",
};

/**
 * The session tab strip (spec Phase 3a).
 *
 * Parallel sessions are only useful if you can see them all at once; a
 * dropdown would hide exactly the session that needs you.
 */
export function SessionTabs({
  sessions,
  activeId,
}: {
  sessions: MissionControlRow[];
  activeId: string;
}) {
  if (sessions.length <= 1) return null;

  return (
    <div
      className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-edge bg-surface"
      data-testid="session-tabs"
    >
      {sessions.map((session) => {
        const active = session.session_id === activeId;
        return (
          <Link
            key={session.session_id}
            href={`/session/${session.session_id}`}
            data-testid={`session-tab-${session.session_id}`}
            data-active={active}
            className={`flex max-w-56 shrink-0 items-center gap-2 border-r border-edge px-3 text-xs ${
              active ? "bg-base text-ink" : "text-ink-faint hover:text-ink-dim"
            }`}
            title={session.task}
          >
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[session.status]} ${
                session.approval_needed ? "pulse-attention" : ""
              }`}
            />
            <span className="truncate">{session.task}</span>
            {session.approval_needed && (
              <span className="shrink-0 text-[10px] text-attention">needs you</span>
            )}
          </Link>
        );
      })}
      <Link
        href="/"
        className="flex shrink-0 items-center px-3 text-xs text-ink-faint hover:text-ink"
        title="All sessions"
      >
        +
      </Link>
    </div>
  );
}
