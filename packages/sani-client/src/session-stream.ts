/**
 * A subscribable session stream with reconnection.
 *
 * Store-shaped rather than hook-shaped so both surfaces can drive it: React
 * binds it with `useSyncExternalStore`, and the VS Code extension host
 * subscribes directly and forwards state to its webview.
 */

import { initialStreamState, reduceEvent, type StreamState } from "./stream.ts";
import type { SaniEvent } from "./types.ts";

/**
 * The slice of the WebSocket API this needs.
 *
 * Handler signatures are intentionally loose: the browser's `WebSocket` and the
 * `ws` package type their events differently, and a stricter shape here would
 * force a cast at both call sites rather than describing what is actually used.
 */
export interface SocketLike {
  close(): void;
  onopen: ((event: any) => any) | null;
  onclose: ((event: any) => any) | null;
  onerror: ((event: any) => any) | null;
  onmessage: ((event: any) => any) | null;
}

export type SocketFactory = (url: string) => SocketLike;

export const RECONNECT_DELAY_MS = 800;

export class SessionStream {
  private socket: SocketLike | null = null;
  private listeners = new Set<(state: StreamState) => void>();
  private retry: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  state: StreamState = initialStreamState;

  private readonly wsUrl: string;
  private readonly createSocket: SocketFactory;
  private readonly reconnectDelayMs: number;

  // Explicit assignment rather than parameter properties: Node's type-stripping
  // rejects those, and running these tests without a build step is worth more
  // than the three saved lines.
  constructor(
    wsUrl: string,
    createSocket: SocketFactory,
    reconnectDelayMs: number = RECONNECT_DELAY_MS,
  ) {
    this.wsUrl = wsUrl;
    this.createSocket = createSocket;
    this.reconnectDelayMs = reconnectDelayMs;
  }

  subscribe(listener: (state: StreamState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getState = (): StreamState => this.state;

  private emit(next: StreamState): void {
    if (next === this.state) return;
    this.state = next;
    for (const listener of this.listeners) listener(next);
  }

  connect(): void {
    // A finished session has nothing further to send; reconnecting would only
    // re-download a log the reducer has already folded.
    if (this.state.ended) return;

    // `connect()` is an explicit request to be connected, so it clears a prior
    // dispose rather than being ignored by one. This matters because React runs
    // effects mount -> cleanup -> mount in development: the adapter memoises the
    // stream per session id, so the same object is disposed and then reconnected.
    // Treating dispose as permanent made that second connect a silent no-op and
    // left the session view blank -- in dev only, which is where it hides longest.
    this.disposed = false;

    // Reconnect from the last sequence seen, so the server replays exactly what
    // was missed. reduceEvent drops any overlap, so this is safe to repeat.
    //
    // wsUrl may already carry a `?token=...` query string (auth enabled), so a
    // bare `?from_seq=` here would produce a second `?` -- a URL every browser
    // WebSocket constructor rejects outright. This only ever showed up with
    // auth on, which the test suite doesn't exercise by default.
    const separator = this.wsUrl.includes("?") ? "&" : "?";
    const socket = this.createSocket(`${this.wsUrl}${separator}from_seq=${this.state.lastSeq}`);
    this.socket = socket;

    socket.onopen = () => this.emit({ ...this.state, connected: true });

    socket.onmessage = (message) => {
      const raw = typeof message.data === "string" ? message.data : String(message.data);
      let event: SaniEvent;
      try {
        event = JSON.parse(raw) as SaniEvent;
      } catch {
        return; // a frame we cannot parse is not a reason to tear down the stream
      }
      this.emit(reduceEvent(this.state, event));
    };

    socket.onclose = () => {
      this.emit({ ...this.state, connected: false });
      if (!this.disposed && !this.state.ended) {
        this.retry = setTimeout(() => this.connect(), this.reconnectDelayMs);
      }
    };

    socket.onerror = () => socket.close();
  }

  dispose(): void {
    this.disposed = true;
    if (this.retry) clearTimeout(this.retry);
    this.socket?.close();
    this.listeners.clear();
  }
}
