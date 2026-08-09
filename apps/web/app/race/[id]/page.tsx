"use client";

import type { RaceBoard, Racer } from "@sani/client";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";
import { StatusPill } from "@/components/StatusBar";
import { Button } from "@/components/ui/Button";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { ApiError, api } from "@/lib/client";
import { springs } from "@/lib/motion";
import { useAmbientState } from "@/lib/useAmbientState";

const POLL_MS = 1500;

/**
 * The race board.
 *
 * N agents on one task, each in its own git worktree. The board's job is to
 * make "which of these do I want" answerable at a glance, so every racer shows
 * the same handful of facts in the same place: how far it got, what it touched,
 * what it cost, and whether it is waiting on you.
 *
 * There is deliberately no "pick the winner for me" button. Choosing is the
 * judgement the human is here for, and a product whose whole argument is
 * keeping the human in the loop should not quietly decide.
 */

function RacerCard({
  racer,
  onKeep,
  busy,
}: {
  racer: Racer;
  onKeep: (label: string) => void;
  busy: boolean;
}) {
  const progress =
    racer.total_steps > 0
      ? Math.min(((racer.current_step ?? 0) + 1) / racer.total_steps, 1)
      : 0;

  return (
    <motion.li layout>
      <GlassPanel
        elevation={1}
        className={`flex h-full flex-col gap-3 rounded-xl p-4 ${
          racer.approval_needed ? "border-attention/50" : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-raised font-mono text-xs font-semibold uppercase text-ink">
            {racer.label}
          </span>
          {racer.status !== "unknown" && <StatusPill status={racer.status} />}
          {racer.approval_needed && (
            <span className="pulse-attention ml-auto rounded-md bg-attention/15 px-2 py-0.5 text-[11px] text-attention">
              needs you
            </span>
          )}
        </div>

        <div className="h-1 overflow-hidden rounded-full bg-edge">
          <motion.div
            className="h-full rounded-full bg-agent"
            animate={{ width: `${Math.max(progress * 100, 2)}%` }}
            transition={springs.settle}
          />
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-[11px]">
          <dt className="text-ink-faint">steps</dt>
          <dd className="text-right text-ink-dim tabular-nums">
            {racer.total_steps > 0
              ? `${(racer.current_step ?? 0) + 1}/${racer.total_steps}`
              : "—"}
          </dd>
          <dt className="text-ink-faint">files</dt>
          <dd className="text-right text-ink-dim tabular-nums">{racer.files_changed}</dd>
          <dt className="text-ink-faint">elapsed</dt>
          <dd className="text-right text-ink-dim tabular-nums">
            {racer.elapsed_s.toFixed(1)}s
          </dd>
          {racer.cost && (
            <>
              <dt className="text-ink-faint">cost</dt>
              <dd className="text-right text-ink-dim tabular-nums">
                {racer.cost.total_usd !== null
                  ? `${racer.cost.estimated ? "~" : ""}$${racer.cost.total_usd.toFixed(4)}`
                  : `${racer.cost.total_tokens.toLocaleString()} tok`}
              </dd>
            </>
          )}
        </dl>

        <p
          className="truncate font-mono text-[10px] text-ink-faint"
          title={racer.branch}
        >
          {racer.branch}
        </p>

        <div className="mt-auto flex gap-2 pt-1">
          <Link href={`/session/${racer.session_id}`} className="flex-1">
            <Button variant="outline" size="sm" className="w-full">
              Open
            </Button>
          </Link>
          <Button
            variant="primary"
            size="sm"
            disabled={busy}
            onClick={() => onKeep(racer.label)}
            title="End the race and keep this racer's branch"
          >
            Keep
          </Button>
        </div>
      </GlassPanel>
    </motion.li>
  );
}

export default function RacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [board, setBoard] = useState<RaceBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState<{
    label: string;
    branch: string;
    worktree: string | null;
  } | null>(null);

  useAmbientState(
    board?.awaiting_approval ? "blocked-on-approval" : board?.running ? "executing" : null,
  );

  const refresh = useCallback(async () => {
    try {
      setBoard(await api.race(id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [id]);

  useEffect(() => {
    refresh();
    // Polled rather than streamed: a race has no single event log, and N
    // sockets to watch N sessions is a lot of machinery for a board that only
    // needs to be roughly current.
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const keep = useCallback(async (label: string) => {
    setBusy(true);
    try {
      const result = await api.discardRace(id, label);
      if (result.kept_branch) {
        setKept({
          label: result.kept ?? label,
          branch: result.kept_branch,
          worktree: result.kept_worktree,
        });
      }
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }, [id, refresh]);

  const discardAll = async () => {
    setBusy(true);
    try {
      await api.discardRace(id, null);
      router.push("/");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
      setBusy(false);
    }
  };

  return (
    <main className="h-full overflow-auto">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <Link
          href="/"
          className="font-mono text-[11px] uppercase tracking-[0.2em] text-ink-faint transition-colors hover:text-ink"
        >
          ← Mission Control
        </Link>

        <header className="mb-8 mt-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {board?.task ?? "Race"}
          </h1>
          <p className="mt-1.5 font-mono text-[11px] text-ink-faint">
            {board
              ? `${board.racers.length} racers · ${board.running} running${
                  board.awaiting_approval > 0
                    ? ` · ${board.awaiting_approval} awaiting you`
                    : ""
                }`
              : "loading…"}
          </p>
          <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-ink-dim">
            Each racer works in its own git worktree, so they cannot see each
            other&apos;s edits. Keeping one removes the rest and leaves its worktree
            in place — the changes there are uncommitted, and nothing is committed or
            merged for you.
          </p>
        </header>

        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mb-6 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-xs text-danger"
            >
              {error}
            </motion.div>
          )}
          {kept && (
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 rounded-xl border border-ok/40 bg-ok/10 px-4 py-3 text-xs leading-relaxed text-ok"
              data-testid="race-outcome"
            >
              Kept racer <strong>{kept.label}</strong>. The other worktrees have been
              removed.
              <br />
              {/* The agent edits the working directory and does not commit, so
                  the change is NOT on the branch tip. Saying "merge the branch"
                  would send someone to an empty ref and lose their work. */}
              Its work is <strong>uncommitted</strong> in{" "}
              <code className="font-mono">{kept.worktree}</code> (branch{" "}
              <code className="font-mono">{kept.branch}</code>). Commit it there before
              merging — nothing has been committed for you.
            </motion.div>
          )}
        </AnimatePresence>

        {/* No entrance animation on this board, on purpose. It polls every
            1.5s and a staggered fade restarts on every refresh -- it never
            settles, and it encodes nothing. `layout` stays, because cards
            genuinely reorder as racers finish. */}
        {board && (
          <motion.ul
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
            data-testid="race-board"
          >
            {board.racers.map((racer) => (
              <RacerCard
                key={racer.session_id}
                racer={racer}
                onKeep={keep}
                busy={busy}
              />
            ))}
          </motion.ul>
        )}

        {board && (
          <div className="mt-8 flex items-center gap-3">
            <Button variant="danger" size="sm" onClick={discardAll} disabled={busy}>
              Discard all
            </Button>
            <span className="text-[11px] text-ink-faint">
              Ends every racer and removes their worktrees.
            </span>
          </div>
        )}
      </div>
    </main>
  );
}
