/**
 * Mirrors the server contract in CLAUDE.md. This file is the only place the
 * wire format is described on the client; if it drifts from the server, that
 * is a bug in one place rather than twelve.
 */

export type SessionStatus =
  | "planning"
  | "executing"
  | "blocked-on-approval"
  | "paused"
  | "complete"
  | "failed"
  | "killed";

export type StepStatus =
  | "pending"
  | "running"
  | "complete"
  | "rejected"
  | "failed"
  | "skipped";

export type EventType =
  | "session.status"
  | "plan.proposed"
  | "plan.step.started"
  | "plan.step.completed"
  | "agent.message.delta"
  | "agent.message.done"
  | "tool.proposed"
  | "approval.required"
  | "approval.resolved"
  | "tool.result"
  | "diff.generated"
  | "context.usage"
  | "rag.retrieved"
  | "session.complete"
  | "session.error";

export interface SaniEvent {
  v: number;
  seq: number;
  session_id: string;
  ts: number;
  type: EventType;
  // Payload shape varies by event type; the stream reducer narrows per branch.
  data: any;
}

export interface Hunk {
  id: string;
  header: string;
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  lines: string[];
}

export interface FileDiff {
  path: string;
  unified: string;
  is_new_file: boolean;
  is_delete: boolean;
  hunks: Hunk[];
}

export interface ProposedAction {
  id: string;
  action_type: string;
  tool: string;
  summary: string;
  step_index: number;
  preview: Record<string, any>;
  diff: FileDiff | null;
}

export interface Decision {
  requires_approval: boolean;
  reason: string;
  action_type: string;
}

export interface PlanStep {
  index: number;
  description: string;
  tool: string;
  params: Record<string, any>;
  status: StepStatus;
  detail: string | null;
}

export interface Plan {
  task: string;
  rationale: string;
  steps: PlanStep[];
}

export interface TrustTier {
  action_type: string;
  auto_approve: boolean;
  consecutive_approvals: number;
  always_confirm: boolean;
  promotion_threshold: number;
}

export interface ContextUsage {
  used_tokens: number;
  limit_tokens: number;
  pct: number;
  should_compact: boolean;
  estimated: boolean;
  model?: string;
}

export interface Session {
  session_id: string;
  task: string;
  workspace: string;
  lifecycle: "foreground" | "background";
  status: SessionStatus;
  tools: string[];
  plan: Plan | null;
  current_step: number | null;
  active_tool: string | null;
  pending_action: ProposedAction | null;
  trust: Record<string, TrustTier>;
  context: ContextUsage;
  error: string | null;
  created_at: number;
  ended_at: number | null;
  elapsed_s: number;
}

export interface RagStatus {
  indexed: boolean;
  chunks: number;
  files: number;
  embedder: { name: string; semantic: boolean };
  store: { kind: string; verified?: boolean };
}

export interface MissionControlRow {
  session_id: string;
  task: string;
  status: SessionStatus;
  lifecycle: string;
  current_step: number | null;
  current_step_description: string | null;
  total_steps: number;
  elapsed_s: number;
  active_tool: string | null;
  approval_needed: boolean;
  pending_action: ProposedAction | null;
  /** Restored from the archive: readable history, no running executor. */
  detached?: boolean;
}

export interface FileEntry {
  path: string;
  name: string;
  type: "file" | "dir";
  size: number | null;
}

export const TERMINAL_STATUSES: SessionStatus[] = ["complete", "failed", "killed"];

export function isTerminal(status: SessionStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}
