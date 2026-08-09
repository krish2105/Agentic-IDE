"use client";

import { useEffect, useState } from "react";
import { credentialWarning } from "@sani/client";
import { BUILD_TIME_SERVER, currentConnection, diagnose, saveConnection } from "@/lib/client";

/**
 * Where the UI points, editable at runtime.
 *
 * Without this, a hosted build is stuck with whatever `NEXT_PUBLIC_SANI_SERVER`
 * was set to when it was compiled -- and the default is loopback, which from a
 * visitor's browser means their own machine. This is the fix for the
 * "cannot reach the server" that a Vercel deploy shows by default.
 */
export function ConnectionPanel({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [server, setServer] = useState("");
  const [token, setToken] = useState("");

  useEffect(() => {
    if (!open) return;
    const connection = currentConnection();
    setServer(connection.server);
    setToken(connection.token);
  }, [open]);

  if (!open) return null;

  const problem = diagnose(server);
  const mixUp = credentialWarning({ server, token });
  const loopback = problem === "loopback-from-hosted";
  const mixed = problem === "insecure-mix";

  return (
    <div
      className="mb-6 rounded-lg border border-edge bg-surface p-4"
      data-testid="connection-panel"
    >
      <div className="mb-3 flex items-center">
        <h2 className="text-sm font-semibold text-ink">Backend connection</h2>
        <button
          onClick={onClose}
          className="ml-auto text-xs text-ink-faint hover:text-ink"
          aria-label="Close connection settings"
        >
          ×
        </button>
      </div>

      <label className="mb-1 block text-[11px] uppercase tracking-wider text-ink-faint">
        Server URL
      </label>
      <input
        value={server}
        onChange={(event) => setServer(event.target.value)}
        placeholder={BUILD_TIME_SERVER}
        data-testid="connection-server"
        className="mb-3 w-full rounded border border-edge bg-base px-3 py-2 font-mono text-xs text-ink outline-none focus:border-edge-strong"
      />

      <label className="mb-1 block text-[11px] uppercase tracking-wider text-ink-faint">
        Auth token{" "}
        <span className="normal-case tracking-normal">
          — only if the server sets <code className="font-mono">SANI_AUTH_TOKEN</code>
        </span>
      </label>
      <input
        value={token}
        onChange={(event) => setToken(event.target.value)}
        type="password"
        placeholder="leave empty for a local, unauthenticated server"
        data-testid="connection-token"
        className="w-full rounded border border-edge bg-base px-3 py-2 font-mono text-xs text-ink outline-none focus:border-edge-strong"
      />

      {/* The two fields are filled from the clipboard one after the other, so
          crossing them is easy — and a URL in the token field yields 401s that
          are indistinguishable from a stale token, which sends you back to fix
          the *server* field over and over. Named here, at the point of entry. */}
      {mixUp && (
        <p
          className="mt-3 text-[11px] leading-relaxed text-attention"
          data-testid="connection-mixup"
        >
          {mixUp}
        </p>
      )}

      {loopback && (
        <p className="mt-3 text-[11px] leading-relaxed text-attention">
          This page is hosted, but the URL points at loopback — which in your
          browser means <em>your own machine</em>, not the server this page came
          from. Expose your backend over an HTTPS tunnel and use that URL.
        </p>
      )}
      {mixed && !loopback && (
        <p className="mt-3 text-[11px] leading-relaxed text-attention">
          This page is HTTPS and the server URL is plain HTTP. The browser will
          block those requests. Use an <code className="font-mono">https://</code> URL.
        </p>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button
          onClick={() => {
            saveConnection({ server, token });
            onSaved();
            onClose();
          }}
          data-testid="connection-save"
          className="rounded bg-ink px-3 py-1.5 text-xs font-medium text-base hover:opacity-90"
        >
          Save and reconnect
        </button>
        <span className="text-[11px] text-ink-faint">
          Stored in this browser only.
        </span>
      </div>
    </div>
  );
}
