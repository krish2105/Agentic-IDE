"use client";

import Link from "next/link";
import type { ContextUsage, SessionStatus } from "@sani/client";

const STATUS_STYLES: Record<SessionStatus, string> = {
  planning: "bg-edge text-ink-dim",
  executing: "bg-edge text-ink",
  "blocked-on-approval": "bg-attention/15 text-attention",
  paused: "bg-edge text-ink-dim",
  complete: "bg-ok/15 text-ok",
  failed: "bg-danger/15 text-danger",
  killed: "bg-danger/15 text-danger",
};

const STATUS_LABELS: Record<SessionStatus, string> = {
  planning: "Planning",
  executing: "Executing",
  "blocked-on-approval": "Needs approval",
  paused: "Paused",
  complete: "Complete",
  failed: "Failed",
  killed: "Killed",
};

export function StatusPill({ status }: { status: SessionStatus }) {
  const live = status === "executing" || status === "planning";
  return (
    <span
      data-testid="status-pill"
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {live && <span className="h-1.5 w-1.5 rounded-full bg-current pulse-attention" />}
      {status === "blocked-on-approval" && (
        <span className="h-1.5 w-1.5 rounded-full bg-current pulse-attention" />
      )}
      {STATUS_LABELS[status]}
    </span>
  );
}

function ContextMeter({ context }: { context: ContextUsage | null }) {
  if (!context) return null;
  const pct = Math.min(context.pct * 100, 100);
  return (
    <div className="flex items-center gap-2" title="Estimated context window usage">
      <span className="text-ink-faint">context</span>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-edge">
        <div
          className={`h-full rounded-full ${context.should_compact ? "bg-attention" : "bg-ink-faint"}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <span className="font-mono text-ink-dim tabular-nums">
        {context.used_tokens.toLocaleString()} / {(context.limit_tokens / 1000).toFixed(0)}k
      </span>
    </div>
  );
}

interface Props {
  task: string;
  status: SessionStatus;
  context: ContextUsage | null;
  workspace: string;
  connected: boolean;
  sandbox: string | null;
  onPause: () => void;
  onResume: () => void;
  onKill: () => void;
  busy: boolean;
}

export function StatusBar({
  task,
  status,
  context,
  workspace,
  connected,
  sandbox,
  onPause,
  onResume,
  onKill,
  busy,
}: Props) {
  const finished = ["complete", "failed", "killed"].includes(status);

  return (
    <header className="flex h-11 shrink-0 items-center gap-4 border-b border-edge bg-surface px-3 text-xs">
      <Link
        href="/"
        className="shrink-0 font-semibold tracking-tight text-ink hover:text-agent"
        title="Back to all sessions"
      >
        Ṣāni&apos; Studio
      </Link>

      <StatusPill status={status} />

      <span className="min-w-0 flex-1 truncate text-ink-dim" title={task}>
        {task}
      </span>

      <ContextMeter context={context} />

      <span className="font-mono text-ink-faint" title={workspace}>
        {sandbox ?? "…"} · {workspace.split("/").slice(-1)[0]}
      </span>

      {/* A finished session closes its stream on purpose, so a red dot there
          would report a fault that did not happen. */}
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          connected ? "bg-ok" : finished ? "bg-ink-faint" : "bg-danger"
        }`}
        title={
          connected
            ? "Stream connected"
            : finished
              ? "Stream closed — session finished"
              : "Stream disconnected — retrying"
        }
        data-testid="connection-dot"
        data-connected={connected}
      />

      <div className="flex shrink-0 items-center gap-1">
        {status === "paused" ? (
          <button
            onClick={onResume}
            disabled={busy}
            className="rounded border border-edge px-2 py-1 hover:border-edge-strong hover:text-ink disabled:opacity-40"
          >
            Resume
          </button>
        ) : (
          <button
            onClick={onPause}
            disabled={busy || finished}
            className="rounded border border-edge px-2 py-1 hover:border-edge-strong hover:text-ink disabled:opacity-40"
          >
            Pause
          </button>
        )}
        <button
          onClick={onKill}
          disabled={busy || finished}
          className="rounded border border-edge px-2 py-1 text-ink-dim hover:border-danger hover:text-danger disabled:opacity-40"
        >
          Kill
        </button>
      </div>
    </header>
  );
}
