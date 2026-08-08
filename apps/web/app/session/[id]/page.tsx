"use client";

import { useCallback, useEffect, useState } from "react";
import { use } from "react";
import { EditorPane, type OpenTab } from "@/components/EditorPane";
import { FileTree } from "@/components/FileTree";
import { RightDock } from "@/components/RightDock";
import { StatusBar } from "@/components/StatusBar";
import { TerminalPanel } from "@/components/TerminalPanel";
import { api } from "@/lib/api";
import type { FileEntry, Session } from "@/lib/types";
import { useSessionStream } from "@/lib/useSessionStream";

export default function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const stream = useSessionStream(id);

  const [session, setSession] = useState<Session | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [tabs, setTabs] = useState<OpenTab[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [terminalCollapsed, setTerminalCollapsed] = useState(false);
  const [sandboxKind, setSandboxKind] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSession(id).then(setSession).catch(() => setSession(null));
  }, [id]);

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

  return (
    <div className="flex h-screen flex-col">
      <StatusBar
        task={session?.task ?? "…"}
        status={stream.status}
        context={stream.context}
        workspace={session?.workspace ?? ""}
        connected={stream.connected}
        sandbox={sandboxKind}
        busy={busy}
        onPause={() => withBusy(() => api.pause(id))}
        onResume={() => withBusy(() => api.resume(id))}
        onKill={() => withBusy(() => api.kill(id))}
      />

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
          chat={stream.chat}
          streaming={stream.streamingMessage}
          steps={stream.steps}
          currentStep={stream.currentStep}
          diffs={stream.diffs}
          pending={stream.pending}
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
    </div>
  );
}
