import type { StreamState } from "@sani/client";
import * as vscode from "vscode";
import { AgentGutter } from "./decorations.ts";
import { OriginalContentProvider, ORIGINAL_SCHEME, showNativeDiff } from "./diff-view.ts";
import { SaniSidebar, type WebviewIntent } from "./sidebar.ts";
import { SessionController } from "./session-controller.ts";

const STATUS_TEXT: Record<string, string> = {
  planning: "$(sync~spin) planning",
  executing: "$(sync~spin) executing",
  "blocked-on-approval": "$(warning) needs approval",
  paused: "$(debug-pause) paused",
  complete: "$(check) complete",
  failed: "$(error) failed",
  killed: "$(circle-slash) killed",
};

/** What `activate` hands back, for integration tests to drive the real thing. */
export interface SaniExtensionApi {
  controller: SessionController;
  openDiff(path: string): Promise<void>;
}

export function activate(context: vscode.ExtensionContext): SaniExtensionApi {
  const controller = new SessionController();
  const originals = new OriginalContentProvider();
  const gutter = new AgentGutter();

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = "sani.missionControl";
  status.text = "$(circuit-board) Ṣāni'";
  status.tooltip = "Ṣāni' Studio — no active session";
  status.show();

  const sidebar = new SaniSidebar(context.extensionUri, controller, (intent) =>
    handleIntent(intent),
  );

  async function handleIntent(intent: WebviewIntent): Promise<void> {
    try {
      switch (intent.type) {
        case "ready":
          sidebar.push(controller.state, controller.sessionId);
          break;
        case "newSession":
          await controller.start(intent.task);
          break;
        case "approve":
          await controller.approve(intent.hunkIds);
          break;
        case "reject":
          await controller.reject();
          break;
        case "openDiff":
          await openDiff(intent.path);
          break;
        case "pause":
          if (controller.sessionId) await controller.api.pause(controller.sessionId);
          break;
        case "resume":
          if (controller.sessionId) await controller.api.resume(controller.sessionId);
          break;
        case "kill":
          if (controller.sessionId) await controller.api.kill(controller.sessionId);
          break;
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Ṣāni': ${describe(error)}`);
    }
  }

  async function openDiff(path: string): Promise<void> {
    const diff = controller.state?.diffs[path];
    if (!diff || !controller.workspaceRoot) return;
    await showNativeDiff(originals, controller.workspaceRoot, diff);
  }

  function onState(state: StreamState): void {
    status.text = `$(circuit-board) Ṣāni' ${STATUS_TEXT[state.status] ?? state.status}`;
    status.tooltip = controller.sessionId
      ? `Session ${controller.sessionId} — ${state.status}`
      : "Ṣāni' Studio";
    status.backgroundColor =
      state.status === "blocked-on-approval"
        ? new vscode.ThemeColor("statusBarItem.warningBackground")
        : undefined;

    gutter.update(state.diffs, controller.workspaceRoot);

    // An approval is the one event worth interrupting for; everything else the
    // user can find in their own time.
    if (state.pending) sidebar.reveal();
  }

  context.subscriptions.push(
    controller,
    originals,
    gutter,
    status,
    vscode.window.registerWebviewViewProvider(SaniSidebar.viewType, sidebar),
    vscode.workspace.registerTextDocumentContentProvider(ORIGINAL_SCHEME, originals),
    controller.onState(onState),
    vscode.window.onDidChangeVisibleTextEditors((editors) =>
      editors.forEach((editor) => gutter.apply(editor)),
    ),

    vscode.commands.registerCommand("sani.newSession", async () => {
      const task = await vscode.window.showInputBox({
        prompt: "What should the agent do?",
        placeHolder: "e.g. add a greeting module and run the tests",
      });
      if (!task?.trim()) return;
      try {
        await controller.start(task.trim());
        sidebar.reveal();
      } catch (error) {
        vscode.window.showErrorMessage(`Ṣāni': ${describe(error)}`);
      }
    }),

    vscode.commands.registerCommand("sani.attachSession", async () => {
      try {
        const board = await controller.api.missionControl();
        if (board.sessions.length === 0) {
          vscode.window.showInformationMessage("Ṣāni': no sessions to attach to.");
          return;
        }
        const picked = await vscode.window.showQuickPick(
          board.sessions.map((row) => ({
            label: row.task,
            description: `${row.status}${row.approval_needed ? " · needs approval" : ""}`,
            detail: row.session_id,
          })),
          { title: "Attach to a Ṣāni' session" },
        );
        if (picked?.detail) {
          controller.attach(picked.detail);
          sidebar.reveal();
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Ṣāni': ${describe(error)}`);
      }
    }),

    vscode.commands.registerCommand("sani.missionControl", async () => {
      try {
        const board = await controller.api.missionControl();
        const lines = board.sessions.map(
          (row) =>
            `${row.approval_needed ? "⚠ " : "  "}${row.status.padEnd(20)} ${row.task}` +
            ` (${row.session_id})`,
        );
        const document = await vscode.workspace.openTextDocument({
          language: "markdown",
          content: [
            "# Ṣāni' Mission Control",
            "",
            `${board.active} active · ${board.awaiting_approval} awaiting approval`,
            "",
            "```",
            ...(lines.length ? lines : ["no sessions"]),
            "```",
          ].join("\n"),
        });
        await vscode.window.showTextDocument(document, { preview: true });
      } catch (error) {
        vscode.window.showErrorMessage(`Ṣāni': ${describe(error)}`);
      }
    }),

    vscode.commands.registerCommand("sani.approve", () => handleIntent({ type: "approve", hunkIds: null })),
    vscode.commands.registerCommand("sani.reject", () => handleIntent({ type: "reject" })),
    vscode.commands.registerCommand("sani.pause", () => handleIntent({ type: "pause" })),
    vscode.commands.registerCommand("sani.resume", () => handleIntent({ type: "resume" })),
    vscode.commands.registerCommand("sani.kill", () => handleIntent({ type: "kill" })),

    vscode.commands.registerCommand("sani.showDiff", async () => {
      const diffs = Object.keys(controller.state?.diffs ?? {});
      if (diffs.length === 0) {
        vscode.window.showInformationMessage("Ṣāni': no agent changes yet.");
        return;
      }
      const path = await vscode.window.showQuickPick(diffs, { title: "Show agent diff" });
      if (path) await openDiff(path);
    }),
  );

  return { controller, openDiff };
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function deactivate(): void {
  /* subscriptions handle teardown */
}
