/**
 * The Ṣāni' sidebar: Chat / Plan / Diffs, matching the web IDE's dock.
 *
 * The webview is a pure renderer. It receives StreamState from the host and
 * posts intents back; it never talks to the server itself, which keeps the
 * "clients are pure consumers" rule true on this surface too.
 */

import type { StreamState } from "@sani/client";
import * as vscode from "vscode";
import type { SessionController } from "./session-controller.ts";

export type WebviewIntent =
  | { type: "ready" }
  | { type: "newSession"; task: string }
  | { type: "approve"; hunkIds: string[] | null }
  | { type: "reject" }
  | { type: "openDiff"; path: string }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "kill" };

export class SaniSidebar implements vscode.WebviewViewProvider {
  static readonly viewType = "sani.sidebar";

  private view: vscode.WebviewView | null = null;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly controller: SessionController,
    private readonly onIntent: (intent: WebviewIntent) => void,
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "dist")],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((intent: WebviewIntent) => this.onIntent(intent));

    const subscription = this.controller.onState((state, sessionId) =>
      this.push(state, sessionId),
    );
    view.onDidDispose(() => {
      subscription.dispose();
      this.view = null;
    });
  }

  push(state: StreamState | null, sessionId: string | null): void {
    void this.view?.webview.postMessage({ type: "state", state, sessionId });
  }

  reveal(): void {
    void vscode.commands.executeCommand("sani.sidebar.focus");
  }

  private html(webview: vscode.Webview): string {
    const script = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "dist", "webview.js"),
    );
    const nonce = Array.from({ length: 32 }, () =>
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".charAt(
        Math.floor(Math.random() * 62),
      ),
    ).join("");

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
  /* Inherit the user's theme rather than imposing one: an extension that
     ignores the editor's colours looks broken next to everything else. */
  :root { --agent: #a78bfa; --attention: var(--vscode-editorWarning-foreground, #f5a524); }
  body {
    padding: 0; margin: 0;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background);
  }
  .tabs { display: flex; border-bottom: 1px solid var(--vscode-panel-border); position: sticky; top: 0;
          background: var(--vscode-sideBar-background); z-index: 2; }
  .tab { padding: 6px 12px; cursor: pointer; border-bottom: 2px solid transparent;
         color: var(--vscode-descriptionForeground); font-size: 11px; text-transform: uppercase;
         letter-spacing: .04em; background: none; border-top: 0; border-left: 0; border-right: 0; }
  .tab.active { color: var(--vscode-foreground); border-bottom-color: var(--vscode-foreground); }
  .body { padding: 10px; }
  .row { display: flex; align-items: center; gap: 6px; }
  .muted { color: var(--vscode-descriptionForeground); }
  .mono { font-family: var(--vscode-editor-font-family); font-size: 11px; }
  .agent { border-left: 2px solid var(--agent); padding-left: 8px; background: rgba(167,139,250,.07); }
  .approval { border: 1px solid var(--attention); border-radius: 4px; padding: 8px; margin-bottom: 12px; }
  .approval h4 { margin: 0 0 4px; color: var(--attention); font-size: 12px; }
  button.action { background: var(--vscode-button-background); color: var(--vscode-button-foreground);
                  border: none; padding: 4px 10px; border-radius: 2px; cursor: pointer; font-size: 12px; }
  button.secondary { background: var(--vscode-button-secondaryBackground);
                     color: var(--vscode-button-secondaryForeground); }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 5px 7px;
                     background: var(--vscode-input-background); color: var(--vscode-input-foreground);
                     border: 1px solid var(--vscode-input-border, transparent); border-radius: 2px; }
  ol { padding-left: 18px; margin: 0; }
  li { margin-bottom: 8px; }
  pre { white-space: pre-wrap; word-break: break-all; margin: 4px 0 0;
        background: var(--vscode-textCodeBlock-background); padding: 5px; border-radius: 2px;
        font-size: 11px; max-height: 180px; overflow: auto; }
  .item { margin-bottom: 9px; font-size: 12px; }
  .diff-link { cursor: pointer; color: var(--vscode-textLink-foreground); }
  /* Risk and critique use VS Code's own semantic colours so they read correctly
     in whatever theme the user actually has. */
  .risk { margin: 6px 0 2px; font-size: 12px; }
  .risk-low { color: var(--vscode-testing-iconPassed, #4ade80); }
  .risk-medium { color: var(--vscode-editorWarning-foreground, #f5a524); }
  .risk-high, .risk-critical { color: var(--vscode-editorError-foreground, #f87171); }
  .critique { margin: 6px 0 2px; font-size: 12px;
              color: var(--vscode-editorWarning-foreground, #f5a524); }
  details { margin-top: 4px; }
  summary { cursor: pointer; }
  .hunk { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
  .ok { color: var(--vscode-testing-iconPassed, #4ade80); }
  .bad { color: var(--vscode-testing-iconFailed, #f87171); }
</style>
</head>
<body>
<div id="root"></div>
<script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }
}
