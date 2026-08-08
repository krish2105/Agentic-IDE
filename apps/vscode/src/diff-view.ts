/**
 * Native diff rendering.
 *
 * Spec Section 6: diffs render through VS Code's own diff editor rather than a
 * webview reimplementation. Everything native stays native -- the user gets
 * their own keybindings, their own inline actions, and a diff view they already
 * know how to read.
 *
 * The "before" side is served from an in-memory provider, reconstructed from
 * the current file plus the hunks the server sent.
 */

import { reconstructOriginal } from "@sani/client";
import type { FileDiff } from "@sani/client";
import * as vscode from "vscode";

export const ORIGINAL_SCHEME = "sani-original";

export class OriginalContentProvider
  implements vscode.TextDocumentContentProvider, vscode.Disposable
{
  private readonly contents = new Map<string, string>();
  private readonly changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.changed.event;

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.path) ?? "";
  }

  set(path: string, content: string): vscode.Uri {
    this.contents.set(path, content);
    const uri = vscode.Uri.from({ scheme: ORIGINAL_SCHEME, path });
    this.changed.fire(uri);
    return uri;
  }

  dispose(): void {
    this.changed.dispose();
    this.contents.clear();
  }
}

export async function showNativeDiff(
  provider: OriginalContentProvider,
  workspaceRoot: string,
  diff: FileDiff,
): Promise<void> {
  const fileUri = vscode.Uri.joinPath(vscode.Uri.file(workspaceRoot), diff.path);

  if (diff.is_delete) {
    // The file is gone, so there is no right-hand side to diff against.
    const original = vscode.Uri.from({ scheme: ORIGINAL_SCHEME, path: `/${diff.path}` });
    provider.set(`/${diff.path}`, deletedContent(diff));
    await vscode.window.showTextDocument(original, { preview: true });
    return;
  }

  let current = "";
  try {
    current = new TextDecoder().decode(await vscode.workspace.fs.readFile(fileUri));
  } catch {
    current = "";
  }

  const originalUri = provider.set(`/${diff.path}`, reconstructOriginal(current, diff));
  await vscode.commands.executeCommand(
    "vscode.diff",
    originalUri,
    fileUri,
    `${diff.path} — agent changes`,
    { preview: true },
  );
}

function deletedContent(diff: FileDiff): string {
  return diff.hunks
    .flatMap((hunk) => hunk.lines)
    .filter((line) => line.startsWith("-") || line.startsWith(" "))
    .map((line) => line.slice(1))
    .join("");
}
