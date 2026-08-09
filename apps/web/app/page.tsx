"use client";

import type { MissionControlRow } from "@sani/client";
import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConnectionPanel } from "@/components/ConnectionPanel";
import { StatusPill } from "@/components/StatusBar";
import { useAppearance } from "@/components/system/ThemeProvider";
import { CommandHint } from "@/components/system/CommandPalette";
import { Button } from "@/components/ui/Button";
import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  ApiError,
  api,
  currentConnection,
  diagnose,
  explainProblem,
  onConnectionChange,
} from "@/lib/client";
import {
  rise,
  springs,
  stagger,
  staggerChild,
  useGatedMotion,
  useMotionAllowed,
} from "@/lib/motion";
import { allows3D } from "@/lib/quality";
import { useAmbientState } from "@/lib/useAmbientState";

const POLL_MS = 2000;

// 3D is always code-split and never blocks the shell from becoming interactive.
const AmbientField = dynamic(() => import("@/components/three/AmbientField"), { ssr: false });
const MissionControl3D = dynamic(() => import("@/components/three/MissionControl3D"), {
  ssr: false,
});

function NewSessionForm({
  onCreated,
  onRaceStarted,
}: {
  onCreated: (id: string) => void;
  onRaceStarted: (raceId: string) => void;
}) {
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 1 means a normal session. Racing is a way of starting a task, not a
  // separate product, so it lives here rather than behind its own screen.
  const [racers, setRacers] = useState(1);
  const variants = useGatedMotion(rise);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!task.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (racers > 1) {
        if (!workspace.trim()) {
          throw new ApiError(
            400,
            "race_unavailable",
            "A race needs a workspace path — it must be a git repository so each agent gets its own worktree.",
          );
        }
        const board = await api.startRace({
          task: task.trim(),
          workspace: workspace.trim(),
          count: racers,
        });
        onRaceStarted(board.race_id);
        return;
      }
      const session = await api.createSession({
        task: task.trim(),
        workspace: workspace.trim() || undefined,
      });
      onCreated(session.session_id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
      setBusy(false);
    }
  };

  return (
    <motion.form
      onSubmit={submit}
      variants={variants}
      initial="hidden"
      animate="visible"
      className="glass-elevated rounded-2xl p-1.5"
    >
      <div className="flex flex-col gap-1.5 md:flex-row">
        <input
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="What should the agent do?"
          data-testid="task-input"
          className="min-w-0 flex-1 rounded-xl bg-base/40 px-4 py-3.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-faint focus:bg-base/70"
        />
        <input
          value={workspace}
          onChange={(event) => setWorkspace(event.target.value)}
          placeholder="Workspace path (optional)"
          data-testid="workspace-input"
          className="rounded-xl bg-base/40 px-4 py-3.5 font-mono text-xs text-ink outline-none transition-colors placeholder:text-ink-faint focus:bg-base/70 md:w-72"
        />
        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={busy || !task.trim()}
          data-testid="create-session"
          className="rounded-xl px-7"
        >
          {busy ? "Starting…" : racers > 1 ? `Race ${racers}` : "Start"}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 px-3 pb-2 pt-2.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
          Agents
        </span>
        {[1, 2, 3, 4].map((count) => (
          <button
            key={count}
            type="button"
            onClick={() => setRacers(count)}
            aria-pressed={racers === count}
            className={`rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors ${
              racers === count
                ? "bg-raised text-ink"
                : "text-ink-faint hover:text-ink-dim"
            }`}
          >
            {count}
          </button>
        ))}
        {racers > 1 && (
          <span className="text-[10px] text-ink-faint">
            {racers} agents race in isolated git worktrees — the workspace must be a repo.
          </span>
        )}
      </div>
      <AnimatePresence>
        {error && (
          <motion.p
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4 pb-2 pt-2 text-xs text-danger"
          >
            {error}
          </motion.p>
        )}
      </AnimatePresence>
    </motion.form>
  );
}

function SessionRow({ row }: { row: MissionControlRow }) {
  return (
    <motion.li variants={staggerChild} layout>
      <Link
        href={`/session/${row.session_id}`}
        data-testid={`session-row-${row.session_id}`}
        className="group flex items-center gap-4 rounded-xl border border-edge bg-surface/60 px-4 py-3 transition-all hover:border-edge-strong hover:bg-surface"
      >
        <StatusPill status={row.status} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-ink">{row.task}</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-ink-faint">
            {row.current_step_description ??
              (row.total_steps ? `${row.total_steps} steps` : "planning")}
          </p>
        </div>
        {row.approval_needed && (
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-attention/15 px-2 py-0.5 text-[11px] text-attention">
            {/* The dot pulses, not the chip. Fading the whole chip took these
                words to 3.18:1 at the trough -- half of every cycle spent below
                AA, on the one label that exists to be noticed. */}
            <span className="pulse-attention h-1.5 w-1.5 rounded-full bg-current" />
            needs approval
          </span>
        )}
        {row.detached && (
          <span
            className="shrink-0 rounded-md bg-edge px-2 py-0.5 text-[11px] text-ink-faint"
            title="Restored from the archive: readable history, no running executor"
          >
            archived
          </span>
        )}
        {row.active_tool && (
          <span className="shrink-0 font-mono text-[11px] text-ink-faint">{row.active_tool}</span>
        )}
        <span className="shrink-0 font-mono text-[11px] text-ink-faint">
          {row.total_steps > 0 &&
            `${(row.current_step ?? row.total_steps) + (row.status === "complete" ? 0 : 1)}/${row.total_steps} · `}
          {row.elapsed_s.toFixed(1)}s
        </span>
      </Link>
    </motion.li>
  );
}

export default function MissionControl() {
  const router = useRouter();
  const { quality } = useAppearance();
  const [rows, setRows] = useState<MissionControlRow[]>([]);
  const [summary, setSummary] = useState({ active: 0, awaiting: 0, store: "memory" });
  const [offline, setOffline] = useState(false);
  const [status, setStatus] = useState<number | null>(null);
  const [showConnection, setShowConnection] = useState(false);
  const [server, setServer] = useState("");
  const [spatial, setSpatial] = useState(true);

  const listVariants = useGatedMotion(stagger);
  const animated = useMotionAllowed();

  // The landing page has no single session, so the ambient field reflects the
  // board: amber and breathing the moment anything is waiting on a human.
  useAmbientState(
    summary.awaiting > 0 ? "blocked-on-approval" : summary.active > 0 ? "executing" : null,
  );

  const refresh = useCallback(async () => {
    try {
      const board = await api.missionControl();
      setRows(board.sessions);
      setSummary({
        active: board.active,
        awaiting: board.awaiting_approval,
        store: board.store?.kind ?? "memory",
      });
      setOffline(false);
    } catch (caught) {
      // A 401 is a different problem from an unreachable server, and telling
      // them apart is the difference between "start the server" and "paste
      // your token".
      setStatus(caught instanceof ApiError ? caught.status : null);
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    setServer(currentConnection().server);
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    const unsubscribe = onConnectionChange(() => {
      setServer(currentConnection().server);
      refresh();
    });
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
  }, [refresh]);

  const problem = diagnose(server, status);
  const canRender3D = allows3D(quality) && rows.length > 0;
  const showSpatial = canRender3D && spatial;

  const openSession = useCallback(
    (sessionId: string) => router.push(`/session/${sessionId}`),
    [router],
  );

  const headline = useMemo(() => "Watch it think.".split(" "), []);

  return (
    <main className="relative h-full overflow-auto">
      <AmbientField />

      <div className="mx-auto max-w-6xl px-6 pb-20 pt-16 md:pt-24">
        <header className="mb-10">
          <div className="mb-5 flex items-center gap-3">
            <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-ink-faint">
              Ṣāni&apos; Studio
            </span>
            <span className="h-px flex-1 bg-edge" />
            <CommandHint />
          </div>

          {/* Kinetic headline: variable weight settles per word. Hero only --
              this treatment never appears in the work surface.

              Under reduced motion the words are simply *there*, at full weight
              and opacity, with no transition at all. Shortening the fade would
              not be enough: a word crossing from transparent to opaque is the
              exact vestibular trigger the preference exists to remove, and it
              is also the state axe measures, so a "quick" fade reads as a
              contrast failure on the largest text on the page. */}
          <h1
            data-testid="landing-hero"
            className="flex flex-wrap gap-x-4 text-5xl leading-[0.95] tracking-tight text-ink md:text-7xl"
          >
            {headline.map((word, index) => (
              <motion.span
                key={word}
                initial={
                  animated
                    ? { opacity: 0, y: 24, fontVariationSettings: '"wght" 300' }
                    : false
                }
                animate={{ opacity: 1, y: 0, fontVariationSettings: '"wght" 700' }}
                transition={animated ? { ...springs.weighty, delay: 0.08 * index } : { duration: 0 }}
                className="inline-block"
              >
                {word}
              </motion.span>
            ))}
          </h1>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.35, duration: 0.5 }}
            className="mt-5 max-w-xl text-[15px] leading-relaxed text-ink-dim"
          >
            Every plan is shown before it runs. Every tool call is disclosed, including
            the ones that were auto-approved. Irreversible actions stop and wait for you —
            at any trust level, with no exceptions.
          </motion.p>
        </header>

        <AnimatePresence>
          {offline && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="mb-6 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-xs leading-relaxed text-danger"
              data-testid="offline-banner"
            >
              {explainProblem(problem, server)}
              {/* Only suggest starting a local server when a local server is
                  actually what this page is trying to reach. On a hosted page
                  that advice sends people to fix the wrong thing. */}
              {problem === "unreachable" && (
                <>
                  {" "}
                  If it should be local, start it with{" "}
                  <code className="font-mono">uv run uvicorn sani_server.app:app --port 8000</code>.
                </>
              )}
              <button
                onClick={() => setShowConnection(true)}
                data-testid="open-connection"
                className="ml-2 underline hover:no-underline"
              >
                Change connection
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <ConnectionPanel
          open={showConnection}
          onClose={() => setShowConnection(false)}
          onSaved={refresh}
        />

        <div className="mb-12">
          <NewSessionForm
            onCreated={openSession}
            onRaceStarted={(raceId) => router.push(`/race/${raceId}`)}
          />
        </div>

        <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-faint">
            Mission Control
          </h2>
          <span className="font-mono text-[11px] text-ink-dim" data-testid="board-summary">
            {rows.length} total · {summary.active} running
            {summary.awaiting > 0 && (
              <span className="text-attention"> · {summary.awaiting} awaiting you</span>
            )}
          </span>

          {canRender3D && (
            <div className="flex items-center gap-1 rounded-lg border border-edge p-0.5">
              <Button
                size="sm"
                variant={spatial ? "outline" : "ghost"}
                onClick={() => setSpatial(true)}
                aria-pressed={spatial}
              >
                Spatial
              </Button>
              <Button
                size="sm"
                variant={!spatial ? "outline" : "ghost"}
                onClick={() => setSpatial(false)}
                aria-pressed={!spatial}
              >
                List
              </Button>
            </div>
          )}

          <button
            onClick={() => setShowConnection((value) => !value)}
            data-testid="connection-toggle"
            className="ml-auto font-mono text-[11px] text-ink-faint transition-colors hover:text-ink"
            title={server}
          >
            {server.replace(/^https?:\/\//, "")}
          </button>
          <span
            className="font-mono text-[11px] text-ink-faint"
            title={
              summary.store === "redis"
                ? "Sessions survive a server restart"
                : "Sessions live in memory and die with the server process"
            }
          >
            store: {summary.store}
          </span>
        </div>

        {rows.length === 0 ? (
          <GlassPanel
            elevation={0}
            animate
            className="rounded-xl border border-dashed border-edge px-4 py-16 text-center text-sm text-ink-faint"
          >
            No sessions yet.
          </GlassPanel>
        ) : showSpatial ? (
          <div className="space-y-3">
            <div className="h-[440px] overflow-hidden rounded-2xl border border-edge bg-base/30">
              <MissionControl3D sessions={rows} onOpen={openSession} />
            </div>
            <p className="text-center font-mono text-[10px] uppercase tracking-wider text-ink-faint">
              depth = recency · glow = activity · halo = awaiting you · click to open
            </p>
            {/* The spatial view is a visualisation, not the record. The list
                stays in the DOM for screen readers and keyboard users. */}
            <ul className="sr-only" data-testid="session-list">
              {rows.map((row) => (
                <li key={row.session_id}>
                  <Link href={`/session/${row.session_id}`}>
                    {row.task} — {row.status}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <motion.ul
            className="space-y-2"
            data-testid="session-list"
            variants={listVariants}
            initial="hidden"
            animate="visible"
          >
            {rows.map((row) => (
              <SessionRow key={row.session_id} row={row} />
            ))}
          </motion.ul>
        )}
      </div>
    </main>
  );
}
