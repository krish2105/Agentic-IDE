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
    if (this.disposed || this.state.ended) return;

    // Reconnect from the last sequence seen, so the server replays exactly what
    // was missed. reduceEvent drops any overlap, so this is safe to repeat.
    const socket = this.createSocket(`${this.wsUrl}?from_seq=${this.state.lastSeq}`);
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
