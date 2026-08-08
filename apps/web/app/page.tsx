"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ConnectionPanel } from "@/components/ConnectionPanel";
import { StatusPill } from "@/components/StatusBar";
import {
  ApiError,
  api,
  currentConnection,
  diagnose,
  explainProblem,
  onConnectionChange,
} from "@/lib/client";
import type { MissionControlRow } from "@sani/client";

const POLL_MS = 2000;

function NewSessionForm({ onCreated }: { onCreated: (id: string) => void }) {
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!task.trim()) return;
    setBusy(true);
    setError(null);
    try {
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
    <form onSubmit={submit} className="rounded-lg border border-edge bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold text-ink">New session</h2>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="What should the agent do?"
          data-testid="task-input"
          className="flex-1 rounded border border-edge bg-base px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-edge-strong"
        />
        <input
          value={workspace}
          onChange={(event) => setWorkspace(event.target.value)}
          placeholder="Workspace path (optional)"
          data-testid="workspace-input"
          className="w-full rounded border border-edge bg-base px-3 py-2 font-mono text-xs text-ink outline-none placeholder:text-ink-faint focus:border-edge-strong sm:w-80"
        />
        <button
          type="submit"
          disabled={busy || !task.trim()}
          data-testid="create-session"
          className="rounded bg-ink px-4 py-2 text-sm font-medium text-base hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Starting…" : "Start"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </form>
  );
}

export default function MissionControl() {
  const router = useRouter();
  const [rows, setRows] = useState<MissionControlRow[]>([]);
  const [summary, setSummary] = useState({ active: 0, awaiting: 0, store: "memory" });
  const [offline, setOffline] = useState(false);
  const [status, setStatus] = useState<number | null>(null);
  const [showConnection, setShowConnection] = useState(false);
  const [server, setServer] = useState("");

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

  return (
    <main className="h-full overflow-auto bg-base">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8">
          <h1 className="text-xl font-semibold tracking-tight text-ink">Ṣāni&apos; Studio</h1>
          <p className="mt-1 text-sm text-ink-dim">
            Agent sessions. Plans are shown before they run, and irreversible actions always
            stop for you.
          </p>
        </header>

        {offline && (
          <div
            className="mb-6 rounded border border-danger/40 bg-danger/10 px-4 py-3 text-xs leading-relaxed text-danger"
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
                <code className="font-mono">
                  uv run uvicorn sani_server.app:app --port 8000
                </code>
                .
              </>
            )}
            <button
              onClick={() => setShowConnection(true)}
              data-testid="open-connection"
              className="ml-2 underline hover:no-underline"
            >
              Change connection
            </button>
          </div>
        )}

        <ConnectionPanel
          open={showConnection}
          onClose={() => setShowConnection(false)}
          onSaved={refresh}
        />

        <div className="mb-8">
          <NewSessionForm onCreated={(id) => router.push(`/session/${id}`)} />
        </div>

        <div className="mb-3 flex items-baseline gap-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Mission Control
          </h2>
          <span className="font-mono text-[11px] text-ink-dim" data-testid="board-summary">
            {rows.length} total · {summary.active} running
            {summary.awaiting > 0 && (
              <span className="text-attention"> · {summary.awaiting} awaiting you</span>
            )}
          </span>
          <button
            onClick={() => setShowConnection((value) => !value)}
            data-testid="connection-toggle"
            className="ml-auto font-mono text-[11px] text-ink-faint hover:text-ink"
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
          <p className="rounded-lg border border-dashed border-edge px-4 py-10 text-center text-sm text-ink-faint">
            No sessions yet.
          </p>
        ) : (
          <ul className="space-y-2" data-testid="session-list">
            {rows.map((row) => (
              <li key={row.session_id}>
                <Link
                  href={`/session/${row.session_id}`}
                  data-testid={`session-row-${row.session_id}`}
                  className="flex items-center gap-4 rounded-lg border border-edge bg-surface px-4 py-3 hover:border-edge-strong"
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
                    <span className="shrink-0 rounded bg-attention/15 px-2 py-0.5 text-[11px] text-attention pulse-attention">
                      needs approval
                    </span>
                  )}
                  {row.detached && (
                    <span
                      className="shrink-0 rounded bg-edge px-2 py-0.5 text-[11px] text-ink-faint"
                      title="Restored from the archive: readable history, no running executor"
                    >
                      archived
                    </span>
                  )}
                  {row.active_tool && (
                    <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                      {row.active_tool}
                    </span>
                  )}
                  <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                    {row.total_steps > 0 &&
                      `${(row.current_step ?? row.total_steps) + (row.status === "complete" ? 0 : 1)}/${row.total_steps} · `}
                    {row.elapsed_s.toFixed(1)}s
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
