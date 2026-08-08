"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { wsUrl } from "./api";
import type {
  ContextUsage,
  Decision,
  FileDiff,
  Plan,
  PlanStep,
  ProposedAction,
  SaniEvent,
  SessionStatus,
} from "./types";
import { isTerminal } from "./types";

/** One entry in the Chat feed. Everything the agent did, in order. */
export interface ChatItem {
  key: string;
  kind: "message" | "proposal" | "result" | "approval" | "status" | "error";
  text: string;
  detail?: string;
  ok?: boolean;
  auto?: boolean;
  actionType?: string;
}

export interface PendingApproval {
  action: ProposedAction;
  decision: Decision;
}

export interface StreamState {
  connected: boolean;
  /** True once a terminal event has arrived; suppresses reconnect attempts. */
  ended: boolean;
  lastSeq: number;
  status: SessionStatus;
  plan: Plan | null;
  steps: PlanStep[];
  currentStep: number | null;
  pending: PendingApproval | null;
  diffs: Record<string, FileDiff>;
  chat: ChatItem[];
  context: ContextUsage | null;
  streamingMessage: string;
  error: string | null;
}

const initialState: StreamState = {
  connected: false,
  ended: false,
  lastSeq: 0,
  status: "planning",
  plan: null,
  steps: [],
  currentStep: null,
  pending: null,
  diffs: {},
  chat: [],
  context: null,
  streamingMessage: "",
  error: null,
};

type Action =
  | { type: "event"; event: SaniEvent }
  | { type: "connected"; value: boolean }
  | { type: "reset" };

function push(chat: ChatItem[], item: ChatItem): ChatItem[] {
  return [...chat, item];
}

function reduceEvent(state: StreamState, event: SaniEvent): StreamState {
  // Replay after a reconnect can overlap; seq is the authority on what is new.
  if (event.seq <= state.lastSeq) return state;
  const next: StreamState = { ...state, lastSeq: event.seq };
  const key = `${event.seq}`;

  switch (event.type) {
    case "session.status":
      next.status = event.data.status;
      return next;

    case "agent.message.delta":
      next.streamingMessage = state.streamingMessage + event.data.text;
      return next;

    case "agent.message.done":
      next.streamingMessage = "";
      next.chat = push(state.chat, {
        key,
        kind: "message",
        text: event.data.text || state.streamingMessage,
      });
      return next;

    case "plan.proposed":
      next.plan = event.data.plan;
      next.steps = event.data.plan.steps;
      return next;

    case "plan.step.started":
      next.currentStep = event.data.step.index;
      next.steps = state.steps.map((s) =>
        s.index === event.data.step.index ? event.data.step : s,
      );
      return next;

    case "plan.step.completed":
      next.steps = state.steps.map((s) =>
        s.index === event.data.step.index ? event.data.step : s,
      );
      return next;

    case "tool.proposed": {
      const action: ProposedAction = event.data.action;
      next.chat = push(state.chat, {
        key,
        kind: "proposal",
        text: action.summary,
        detail: action.action_type,
        actionType: action.action_type,
      });
      return next;
    }

    case "approval.required":
      next.pending = { action: event.data.action, decision: event.data.decision };
      return next;

    case "approval.resolved":
      next.pending = null;
      // Auto-approvals are disclosed but not narrated -- the tool.proposed
      // entry above already showed what happened. Only decisions a human made
      // get their own line in the feed.
      if (event.data.auto) return next;
      next.chat = push(state.chat, {
        key,
        kind: "approval",
        text: event.data.approved ? "You approved this action" : "You rejected this action",
        detail: event.data.note ?? undefined,
        ok: event.data.approved,
        auto: false,
      });
      return next;

    case "tool.result":
      next.chat = push(state.chat, {
        key,
        kind: "result",
        text: event.data.result.summary,
        detail: event.data.result.output?.slice(0, 2000) || undefined,
        ok: event.data.result.ok,
      });
      return next;

    case "diff.generated": {
      const diff: FileDiff = event.data.diff;
      next.diffs = { ...state.diffs, [diff.path]: diff };
      return next;
    }

    case "context.usage":
      next.context = event.data;
      return next;

    case "session.complete":
      next.ended = true;
      next.status = event.data.status;
      next.chat = push(state.chat, {
        key,
        kind: "status",
        text:
          event.data.status === "killed"
            ? "Session terminated"
            : `Session complete in ${event.data.elapsed_s}s`,
        ok: event.data.status !== "killed",
      });
      return next;

    case "session.error":
      next.ended = true;
      next.status = "failed";
      next.error = event.data.error;
      next.chat = push(state.chat, {
        key,
        kind: "error",
        text: "Session failed",
        detail: event.data.error,
        ok: false,
      });
      return next;

    default:
      return next;
  }
}

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case "event":
      return reduceEvent(state, action.event);
    case "connected":
      return { ...state, connected: action.value };
    case "reset":
      return initialState;
  }
}

const RECONNECT_DELAY_MS = 800;

/**
 * Subscribe to a session's event stream.
 *
 * Reconnection is the reason this hook exists rather than a plain useEffect:
 * on a drop it reopens with `?from_seq=<lastSeq>` so the server replays exactly
 * what was missed. The seq guard in the reducer makes that idempotent, so an
 * overlapping replay cannot double-apply an event.
 */
export function useSessionStream(sessionId: string | null) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const socketRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);
  const endedRef = useRef(false);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  lastSeqRef.current = state.lastSeq;
  endedRef.current = state.ended;

  useEffect(() => {
    if (!sessionId) return;
    let disposed = false;

    const connect = () => {
      if (disposed || endedRef.current) return;

      const socket = new WebSocket(
        wsUrl(`/session/${sessionId}/stream?from_seq=${lastSeqRef.current}`),
      );
      socketRef.current = socket;

      socket.onopen = () => dispatch({ type: "connected", value: true });
      socket.onmessage = (message) =>
        dispatch({ type: "event", event: JSON.parse(message.data) as SaniEvent });
      socket.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!disposed && !endedRef.current) {
          retryRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      disposed = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      socketRef.current?.close();
    };
  }, [sessionId]);

  const agentTouchedPaths = useMemo(() => new Set(Object.keys(state.diffs)), [state.diffs]);

  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  return {
    ...state,
    agentTouchedPaths,
    isTerminal: isTerminal(state.status),
    reset,
  };
}
