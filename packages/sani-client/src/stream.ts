/**
 * The event protocol, turned into UI state.
 *
 * Pure and framework-free on purpose: this is the piece both clients share, so
 * the VS Code sidebar and the web IDE cannot drift in how they interpret a
 * session. A bug here is one bug, not two that disagree.
 */

import type {
  ContextUsage,
  Decision,
  FileDiff,
  Plan,
  PlanStep,
  ProposedAction,
  SaniEvent,
  SessionStatus,
} from "./types.ts";

export interface ChatItem {
  key: string;
  kind: "message" | "proposal" | "result" | "approval" | "status" | "error" | "retrieval";
  text: string;
  detail?: string;
  ok?: boolean;
  auto?: boolean;
  actionType?: string;
  /** Where the command ran, when the item came from a shell action. */
  runsIn?: string;
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
  /** Labels of the code chunks retrieved before planning, if any. */
  retrieved: string[];
  error: string | null;
}

export const initialStreamState: StreamState = {
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
  retrieved: [],
  error: null,
};

function push(chat: ChatItem[], item: ChatItem): ChatItem[] {
  return [...chat, item];
}

/**
 * Fold one event into the state.
 *
 * Events at or below `lastSeq` are ignored, which is what makes reconnection
 * safe: the server replays from a sequence number and any overlap is dropped
 * rather than double-applied.
 */
export function reduceEvent(state: StreamState, event: SaniEvent): StreamState {
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
      next.steps = state.steps.map((step) =>
        step.index === event.data.step.index ? event.data.step : step,
      );
      return next;

    case "plan.step.completed":
      next.steps = state.steps.map((step) =>
        step.index === event.data.step.index ? event.data.step : step,
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
        runsIn: action.preview?.runs_in?.kind,
      });
      return next;
    }

    case "approval.required":
      next.pending = { action: event.data.action, decision: event.data.decision };
      return next;

    case "approval.resolved":
      next.pending = null;
      // Auto-approvals are disclosed but not narrated: the tool.proposed entry
      // already showed what happened. Only decisions a human made get a line.
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
        runsIn: event.data.result.data?.runs_in,
      });
      return next;

    case "diff.generated": {
      const diff: FileDiff = event.data.diff;
      next.diffs = { ...state.diffs, [diff.path]: diff };
      return next;
    }

    case "rag.retrieved":
      // Shown, not hidden: code that silently steered the plan is exactly what
      // the user is entitled to see.
      next.retrieved = event.data.chunks ?? [];
      next.chat = push(state.chat, {
        key,
        kind: "retrieval",
        text: `Read ${event.data.chunks.length} snippet${
          event.data.chunks.length === 1 ? "" : "s"
        } from the codebase`,
        detail: (event.data.chunks as string[]).join("\n"),
      });
      return next;

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

export function agentTouchedPaths(state: StreamState): string[] {
  return Object.keys(state.diffs);
}
