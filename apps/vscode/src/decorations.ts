/**
 * Gutter marks on agent-authored lines (spec Section 6).
 *
 * Uses the accent reserved for agent origin, so the same glance-level
 * distinction the web IDE gives you works in the native editor too.
 */

import { agentAuthoredLines, toLineRanges } from "@sani/client";
import type { FileDiff } from "@sani/client";
import * as vscode from "vscode";

const AGENT_ACCENT = "#a78bfa";

export class AgentGutter implements vscode.Disposable {
  private readonly decoration = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    overviewRulerColor: AGENT_ACCENT,
    overviewRulerLane: vscode.OverviewRulerLane.Left,
    borderWidth: "0 0 0 2px",
    borderStyle: "solid",
    borderColor: AGENT_ACCENT,
    backgroundColor: "rgba(167, 139, 250, 0.07)",
  });

  private diffs: Record<string, FileDiff> = {};
  private workspaceRoot: string | null = null;

  update(diffs: Record<string, FileDiff>, workspaceRoot: string | null): void {
    this.diffs = diffs;
    this.workspaceRoot = workspaceRoot;
    for (const editor of vscode.window.visibleTextEditors) this.apply(editor);
  }

  apply(editor: vscode.TextEditor): void {
    const enabled = vscode.workspace
      .getConfiguration("sani")
      .get<boolean>("showGutterMarks", true);

    const relative = this.relativePath(editor.document.uri);
    const diff = enabled && relative ? this.diffs[relative] : undefined;
    if (!diff) {
      editor.setDecorations(this.decoration, []);
      return;
    }

    const ranges = toLineRanges(agentAuthoredLines(diff)).map(
      ([start, end]) =>
        new vscode.Range(
          new vscode.Position(start, 0),
          new vscode.Position(Math.min(end, editor.document.lineCount - 1), 0),
        ),
    );
    editor.setDecorations(this.decoration, ranges);
  }

  private relativePath(uri: vscode.Uri): string | null {
    if (!this.workspaceRoot || uri.scheme !== "file") return null;
    const root = this.workspaceRoot.endsWith("/")
      ? this.workspaceRoot
      : `${this.workspaceRoot}/`;
    return uri.fsPath.startsWith(root) ? uri.fsPath.slice(root.length) : null;
  }

  dispose(): void {
    this.decoration.dispose();
  }
}
