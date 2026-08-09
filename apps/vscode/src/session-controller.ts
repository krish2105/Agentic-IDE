/**
 * Owns the live session for the whole extension.
 *
 * The extension host holds the WebSocket rather than the webview, for two
 * reasons: a webview is disposed whenever the sidebar is hidden, which would
 * drop the stream every time the user looks at something else, and the native
 * integrations (diff editor, gutter marks, status bar) live out here anyway.
 */

import { SessionStream, createApi, type SaniApi, type StreamState } from "@sani/client";
import * as vscode from "vscode";
import WebSocket from "ws";

export type StateListener = (state: StreamState, sessionId: string | null) => void;

export class SessionController implements vscode.Disposable {
  private stream: SessionStream | null = null;
  private listeners = new Set<StateListener>();
  private unsubscribe: (() => void) | null = null;

  sessionId: string | null = null;
  workspaceRoot: string | null = null;
  state: StreamState | null = null;

  get api(): SaniApi {
    const settings = vscode.workspace.getConfiguration("sani");
    const configured = settings.get<string>("serverUrl", "http://127.0.0.1:8000");
    // The token is what makes a non-loopback server usable at all: the moment
    // the backend is reached over a tunnel it must set SANI_AUTH_TOKEN, because
    // the shell adapter executes commands. `createApi` already threads it onto
    // both HTTP headers and the `?token=` the WebSocket needs -- the extension
    // simply never passed one, so it 401'd against any authenticated server.
    const token = settings.get<string>("authToken", "").trim();
    return createApi(configured, token ? { token } : undefined);
  }

  onState(listener: StateListener): vscode.Disposable {
    this.listeners.add(listener);
    if (this.state) listener(this.state, this.sessionId);
    return new vscode.Disposable(() => this.listeners.delete(listener));
  }

  private publish(state: StreamState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state, this.sessionId);
  }

  async start(task: string): Promise<string> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      throw new Error("Open a folder before starting a session — the agent needs a workspace.");
    }

    const session = await this.api.createSession({ task, workspace: folder.uri.fsPath });
    this.attach(session.session_id, folder.uri.fsPath);
    return session.session_id;
  }

  attach(sessionId: string, workspaceRoot?: string): void {
    this.detach();
    this.sessionId = sessionId;
    this.workspaceRoot =
      workspaceRoot ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? null;

    // `ws` and the browser WebSocket differ enough that the shared stream takes
    // a factory; this is the whole of the platform-specific glue.
    this.stream = new SessionStream(
      this.api.wsUrl(`/session/${sessionId}/stream`),
      (url) => new WebSocket(url),
    );
    this.unsubscribe = this.stream.subscribe((state) => this.publish(state));
    this.stream.connect();
    this.publish(this.stream.getState());
  }

  detach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.stream?.dispose();
    this.stream = null;
    this.sessionId = null;
    this.state = null;
  }

  async approve(hunkIds: string[] | null = null): Promise<void> {
    const pending = this.state?.pending;
    if (!this.sessionId || !pending) return;
    await this.api.approve(this.sessionId, pending.action.id, hunkIds);
  }

  async reject(reason?: string): Promise<void> {
    const pending = this.state?.pending;
    if (!this.sessionId || !pending) return;
    await this.api.reject(this.sessionId, pending.action.id, reason);
  }

  dispose(): void {
    this.detach();
    this.listeners.clear();
  }
}
