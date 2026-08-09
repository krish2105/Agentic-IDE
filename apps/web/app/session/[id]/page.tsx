"use client";

import { useCallback, useEffect, useState } from "react";
import { use } from "react";
import { EditorPane, type OpenTab } from "@/components/EditorPane";
import { FileTree } from "@/components/FileTree";
import { RightDock } from "@/components/RightDock";
import { SessionTabs } from "@/components/SessionTabs";
import { StatusBar } from "@/components/StatusBar";
import { TerminalPanel } from "@/components/TerminalPanel";
import { api } from "@/lib/client";
import type { FileEntry, MissionControlRow, Session, TrustTier } from "@sani/client";
import { useSessionStream } from "@/lib/useSessionStream";
import { useReplay } from "@/lib/useReplay";
import { useAmbientState } from "@/lib/useAmbientState";
import { useRegisterCommands } from "@/lib/commands";
import { ReplayScrubber } from "@/components/ReplayScrubber";

export default function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const stream = useSessionStream(id);
  const replay = useReplay(id, stream.ended);

  // While scrubbing, every panel reads the reconstructed past instead of the
  // live present. One swap here rather than a replay branch in each panel.
  const view = replay.state ?? stream;

  // The shell breathes with whatever is being shown -- live status, or the
  // status at the scrubbed moment.
  useAmbientState(view.status);

  const [session, setSession] = useState<Session | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [tabs, setTabs] = useState<OpenTab[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [terminalCollapsed, setTerminalCollapsed] = useState(false);
  const [sandboxKind, setSandboxKind] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [siblings, setSiblings] = useState<MissionControlRow[]>([]);
  const [trust, setTrust] = useState<Record<string, TrustTier>>({});

  useEffect(() => {
    api
      .getSession(id)
      .then((loaded) => {
        setSession(loaded);
        setTrust(loaded.trust);
      })
      .catch(() => setSession(null));
  }, [id]);

  // The tab strip needs to know about sessions this page did not create.
  useEffect(() => {
    const load = () =>
      api
        .missionControl()
        .then((board) => setSiblings(board.sessions))
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  // Trust changes as the agent earns it, so re-read it whenever the stream
  // says something was decided rather than only on load.
  const resolvedCount = stream.chat.filter((item) => item.kind === "approval").length;
  useEffect(() => {
    api
      .getSession(id)
      .then((loaded) => setTrust(loaded.trust))
      .catch(() => undefined);
  }, [id, resolvedCount, stream.status]);

  const refreshTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      setEntries((await api.files(id)).entries);
    } catch {
      /* the session may have been killed; the status bar already says so */
    } finally {
      setTreeLoading(false);
    }
  }, [id]);

  useEffect(() => {
    refreshTree();
  }, [refreshTree]);

  // The agent writing a file is the one moment the tree is guaranteed stale.
  const diffCount = Object.keys(stream.diffs).length;
  useEffect(() => {
    if (diffCount > 0) refreshTree();
  }, [diffCount, refreshTree]);

  // Reload an open tab when the agent rewrites the file underneath it, unless
  // the human has unsaved edits -- silently discarding those would be theft.
  useEffect(() => {
    for (const path of Object.keys(stream.diffs)) {
      const open = tabs.find((tab) => tab.path === path);
      if (!open || open.dirty) continue;
      api
        .readFile(id, path)
        .then((file) =>
          setTabs((current) =>
            current.map((tab) =>
              tab.path === path && !tab.dirty
                ? { ...tab, content: file.content ?? tab.content }
                : tab,
            ),
          ),
        )
        .catch(() => undefined);
    }
  }, [diffCount, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const openFile = useCallback(
    async (path: string) => {
      setActivePath(path);
      if (tabs.some((tab) => tab.path === path)) return;
      try {
        const file = await api.readFile(id, path);
        const note = file.binary
          ? "Binary file — not shown"
          : file.too_large
            ? "File too large to open"
            : undefined;
        setTabs((current) => [
          ...current,
          { path, content: file.content ?? "", dirty: false, readOnly: Boolean(note), note },
        ]);
      } catch {
        /* unreadable file: leave the tab unopened rather than showing a lie */
        setActivePath(null);
      }
    },
    [id, tabs],
  );

  const saveFile = useCallback(
    async (path: string) => {
      const tab = tabs.find((entry) => entry.path === path);
      if (!tab || tab.readOnly) return;
      await api.saveFile(id, path, tab.content);
      setTabs((current) =>
        current.map((entry) => (entry.path === path ? { ...entry, dirty: false } : entry)),
      );
      refreshTree();
    },
    [id, tabs, refreshTree],
  );

  const withBusy = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
    } finally {
      setBusy(false);
    }
  };

  const pendingActionId = stream.pending?.action.id;

  const toggleTrust = (actionType: string, autoApprove: boolean) =>
    withBusy(async () => {
      try {
        const updated = await api.setTrust(id, actionType, autoApprove);
        setTrust(updated.tiers);
      } catch {
        // The server refuses locked tiers; the panel already shows them locked.
      }
    });

  // Everything this session can do, reachable from ⌘K. Registered here rather
  // than in the palette so a command can never outlive the surface that owns it.
  useRegisterCommands(
    `session:${id}`,
    [
      {
        id: "session:approve",
        label: "Approve pending action",
        group: "Review" as const,
        keywords: "accept allow yes",
        disabled: !pendingActionId,
        run: () => {
          if (pendingActionId) void withBusy(() => api.approve(id, pendingActionId, null));
        },
      },
      {
        id: "session:reject",
        label: "Reject pending action",
        group: "Review" as const,
        keywords: "deny refuse no",
        disabled: !pendingActionId,
        run: () => {
          if (pendingActionId) void withBusy(() => api.reject(id, pendingActionId));
        },
      },
      {
        id: "session:replay",
        label: replay.active ? "Exit replay — back to live" : "Replay this session",
        group: "Review" as const,
        keywords: "timeline scrub history rewind time travel",
        run: () => (replay.active ? replay.exit() : replay.enter()),
      },
      {
        id: "session:pause",
        label: "Pause session",
        group: "Session" as const,
        keywords: "halt suspend",
        run: () => withBusy(() => api.pause(id)),
      },
      {
        id: "session:resume",
        label: "Resume session",
        group: "Session" as const,
        keywords: "continue unpause",
        run: () => withBusy(() => api.resume(id)),
      },
      {
        id: "session:kill",
        label: "Kill session",
        group: "Danger" as const,
        keywords: "stop terminate abort",
        run: () => withBusy(() => api.kill(id)),
      },
    ],
    [id, pendingActionId, replay.active],
  );

  return (
    <div className="flex h-screen flex-col">
      <StatusBar
        task={session?.task ?? "…"}
        status={view.status}
        context={view.context}
        workspace={session?.workspace ?? ""}
        connected={stream.connected}
        sandbox={sandboxKind}
        busy={busy}
        onPause={() => withBusy(() => api.pause(id))}
        onResume={() => withBusy(() => api.resume(id))}
        onKill={() => withBusy(() => api.kill(id))}
        replayActive={replay.active}
        onReplay={() => (replay.active ? replay.exit() : replay.enter())}
      />

      <SessionTabs sessions={siblings} activeId={id} />

      <div className="flex min-h-0 flex-1">
        <FileTree
          entries={entries}
          activePath={activePath}
          agentTouchedPaths={stream.agentTouchedPaths}
          onOpen={openFile}
          onRefresh={refreshTree}
          loading={treeLoading}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <EditorPane
            tabs={tabs}
            activePath={activePath}
            agentTouchedPaths={stream.agentTouchedPaths}
            onSelect={setActivePath}
            onClose={(path) => {
              setTabs((current) => current.filter((tab) => tab.path !== path));
              setActivePath((current) => (current === path ? null : current));
            }}
            onChange={(path, content) =>
              setTabs((current) =>
                current.map((tab) =>
                  tab.path === path ? { ...tab, content, dirty: true } : tab,
                ),
              )
            }
            onSave={saveFile}
          />
          <TerminalPanel
            sessionId={id}
            collapsed={terminalCollapsed}
            onToggle={() => setTerminalCollapsed((value) => !value)}
            onSandbox={setSandboxKind}
          />
        </div>

        <RightDock
          chat={view.chat}
          streaming={view.streamingMessage}
          steps={view.steps}
          currentStep={view.currentStep}
          diffs={view.diffs}
          pending={replay.active ? null : stream.pending}
          trust={trust}
          onTrustToggle={toggleTrust}
          srcFor={(path) => api.rawFileUrl(id, path)}
          busy={busy}
          onApprove={(hunkIds) =>
            pendingActionId &&
            withBusy(() => api.approve(id, pendingActionId, hunkIds))
          }
          onReject={() =>
            pendingActionId && withBusy(() => api.reject(id, pendingActionId))
          }
        />
      </div>

      <ReplayScrubber replay={replay} />
    </div>
  );
}
