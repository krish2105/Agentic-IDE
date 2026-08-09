"use client";

import type { ContextUsage, SessionStatus } from "@sani/client";
import { motion } from "motion/react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { springs } from "@/lib/motion";

const STATUS_STYLES: Record<SessionStatus, string> = {
  planning: "bg-edge text-ink-dim",
  executing: "bg-agent/15 text-agent",
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
  const waiting = status === "blocked-on-approval";
  return (
    <span
      data-testid="status-pill"
      data-status={status}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {(live || waiting) && (
        <span className="pulse-attention h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {STATUS_LABELS[status]}
    </span>
  );
}

function ContextMeter({ context }: { context: ContextUsage | null }) {
  if (!context) return null;
  const pct = Math.min(context.pct * 100, 100);
  return (
    <div
      className="hidden items-center gap-2 xl:flex"
      title={
        context.estimated
          ? "Context window usage (estimated from character count)"
          : "Context window usage"
      }
    >
      <span className="text-ink-faint">context</span>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-edge">
        <motion.div
          className={`h-full rounded-full ${
            context.should_compact ? "bg-attention" : "bg-agent"
          }`}
          animate={{ width: `${Math.max(pct, 2)}%` }}
          transition={springs.settle}
        />
      </div>
      <span className="font-mono tabular-nums text-ink-dim">
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
  onReplay?: () => void;
  replayActive?: boolean;
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
  onReplay,
  replayActive,
  busy,
}: Props) {
  const finished = ["complete", "failed", "killed"].includes(status);

  return (
    <header className="glass-elevated flex h-11 shrink-0 items-center gap-3 rounded-none border-x-0 border-t-0 px-3 text-xs">
      <Link
        href="/"
        className="shrink-0 font-semibold tracking-tight text-ink transition-colors hover:text-agent"
        title="Back to all sessions"
      >
        Ṣāni&apos; Studio
      </Link>

      <StatusPill status={status} />

      <span className="min-w-0 flex-1 truncate text-ink-dim" title={task}>
        {task}
      </span>

      <ContextMeter context={context} />

      <span className="hidden shrink-0 font-mono text-ink-faint lg:inline" title={workspace}>
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
        {onReplay && (
          <Button
            size="sm"
            variant={replayActive ? "outline" : "ghost"}
            onClick={onReplay}
            data-testid="replay-toggle"
            title="Scrub through everything this session did"
          >
            {replayActive ? "Live" : "Replay"}
          </Button>
        )}
        {status === "paused" ? (
          <Button size="sm" variant="outline" onClick={onResume} disabled={busy}>
            Resume
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={onPause} disabled={busy || finished}>
            Pause
          </Button>
        )}
        <Button size="sm" variant="danger" onClick={onKill} disabled={busy || finished}>
          Kill
        </Button>
      </div>
    </header>
  );
}
