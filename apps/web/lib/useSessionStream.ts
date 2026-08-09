"use client";

import { SessionStream, type StreamState } from "@sani/client";
import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { wsUrl } from "./client";

export type { ChatItem, PendingApproval, StreamState } from "@sani/client";

/**
 * React binding over the shared SessionStream.
 *
 * All the interesting behaviour -- the reducer, reconnecting from the last
 * sequence, dropping replayed events -- lives in @sani/client and is shared
 * with the VS Code extension. This hook is only the React adapter.
 */
export function useSessionStream(sessionId: string | null) {
  const streamRef = useRef<SessionStream | null>(null);

  const stream = useMemo(() => {
    if (!sessionId) return null;
    return new SessionStream(
      wsUrl(`/session/${sessionId}/stream`),
      (url) => new WebSocket(url),
    );
  }, [sessionId]);

  streamRef.current = stream;

  useEffect(() => {
    if (!stream) return;
    stream.connect();
    return () => stream.dispose();
  }, [stream]);

  const subscribe = useCallback(
    (onChange: () => void) => stream?.subscribe(onChange) ?? (() => {}),
    [stream],
  );

  const getSnapshot = useCallback(
    () => stream?.getState() ?? EMPTY_STATE,
    [stream],
  );

  const state = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY_STATE);
  const agentTouchedPaths = useMemo(() => new Set(Object.keys(state.diffs)), [state.diffs]);

  return { ...state, agentTouchedPaths };
}

const EMPTY_STATE: StreamState = {
  connected: false,
  ended: false,
  lastSeq: 0,
  status: "planning",
  plan: null,
  steps: [],
  currentStep: null,
  pending: null,
  riskByAction: {},
  critiqueByAction: {},
  diffs: {},
  chat: [],
  context: null,
  streamingMessage: "",
  retrieved: [],
  error: null,
};
