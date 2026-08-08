"use client";

import { useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

interface Props {
  sessionId: string;
  collapsed: boolean;
  onToggle: () => void;
  onSandbox: (kind: string) => void;
}

export function TerminalPanel({ sessionId, collapsed, onToggle, onSandbox }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<{ fit: () => void } | null>(null);
  const [status, setStatus] = useState<"connecting" | "ready" | "exited" | "error">(
    "connecting",
  );

  useEffect(() => {
    if (collapsed || !hostRef.current) return;
    let disposed = false;
    let terminal: any;
    let observer: ResizeObserver | undefined;

    (async () => {
      // xterm touches `window` at import time, so it can only be loaded here.
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      await import("@xterm/xterm/css/xterm.css");
      if (disposed || !hostRef.current) return;

      terminal = new Terminal({
        fontSize: 12,
        fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
        cursorBlink: true,
        convertEol: false,
        theme: {
          background: "#0b0d12",
          foreground: "#e6e9ef",
          cursor: "#a78bfa",
          selectionBackground: "#333b4a",
        },
      });

      const fit = new FitAddon();
      terminal.loadAddon(fit);
      terminal.open(hostRef.current);
      fit.fit();
      fitRef.current = fit;

      const socket = new WebSocket(
        wsUrl(`/session/${sessionId}/terminal?cols=${terminal.cols}&rows=${terminal.rows}`),
      );
      socketRef.current = socket;

      socket.onmessage = (message) => {
        const frame = JSON.parse(message.data);
        if (frame.type === "output") terminal.write(frame.data);
        else if (frame.type === "ready") {
          setStatus("ready");
          onSandbox(frame.sandbox.kind);
        } else if (frame.type === "exit") {
          setStatus("exited");
          terminal.write("\r\n\x1b[2m[process exited]\x1b[0m\r\n");
        } else if (frame.type === "error") {
          setStatus("error");
          terminal.write(`\r\n\x1b[31m${frame.data}\x1b[0m\r\n`);
        }
      };
      socket.onclose = () => setStatus((s) => (s === "ready" ? "exited" : s));
      socket.onerror = () => setStatus("error");

      terminal.onData((data: string) => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "input", data }));
        }
      });

      observer = new ResizeObserver(() => {
        try {
          fit.fit();
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(
              JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }),
            );
          }
        } catch {
          /* the host element can be mid-teardown */
        }
      });
      observer.observe(hostRef.current);
    })();

    return () => {
      disposed = true;
      observer?.disconnect();
      socketRef.current?.close();
      terminal?.dispose();
    };
  }, [sessionId, collapsed, onSandbox]);

  return (
    <div
      className={`flex shrink-0 flex-col border-t border-edge bg-base ${collapsed ? "h-8" : "h-56"}`}
    >
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-edge bg-surface px-3">
        <button
          onClick={onToggle}
          data-testid="terminal-toggle"
          className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint hover:text-ink"
        >
          {collapsed ? "▸" : "▾"} Terminal
        </button>
        {!collapsed && (
          <span className="font-mono text-[11px] text-ink-faint" data-testid="terminal-status">
            {status}
          </span>
        )}
      </div>
      <div
        ref={hostRef}
        data-testid="terminal-host"
        className={`min-h-0 flex-1 px-2 py-1 ${collapsed ? "hidden" : ""}`}
      />
    </div>
  );
}
