"use client";

import { useEffect, useRef, useState } from "react";
import type { FileDiff, PlanStep, StepStatus, TrustTier } from "@sani/client";
import type { ChatItem, PendingApproval } from "@/lib/useSessionStream";
import { ApprovalCard } from "./ApprovalCard";
import { CognitionPanel } from "./CognitionPanel";
import { DiffView } from "./DiffView";
import { TrustPanel } from "./TrustPanel";

type Tab = "chat" | "plan" | "graph" | "diffs" | "trust";

const STEP_MARKS: Record<StepStatus, { glyph: string; className: string }> = {
  pending: { glyph: "○", className: "text-ink-faint" },
  running: { glyph: "◐", className: "text-ink" },
  complete: { glyph: "●", className: "text-ok" },
  rejected: { glyph: "⊘", className: "text-attention" },
  failed: { glyph: "✕", className: "text-danger" },
  skipped: { glyph: "–", className: "text-ink-faint" },
};

function ChatFeed({ items, streaming }: { items: ChatItem[]; streaming: string }) {
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [items.length, streaming]);

  return (
    <div className="space-y-2" data-testid="chat-feed">
      {items.map((item) => {
        if (item.kind === "message") {
          return (
            <div
              key={item.key}
              className="agent-line rounded-r bg-agent/[0.07] py-2 pl-3 pr-2 text-xs leading-relaxed text-ink"
            >
              {item.text}
            </div>
          );
        }
        if (item.kind === "proposal") {
          return (
            <div key={item.key} className="flex items-baseline gap-2 px-1 text-xs">
              <span className="text-ink-faint">→</span>
              <span className="min-w-0 flex-1 truncate font-mono text-ink-dim">{item.text}</span>
              <code className="shrink-0 text-[10px] text-ink-faint">{item.detail}</code>
            </div>
          );
        }
        if (item.kind === "retrieval") {
          return (
            <details key={item.key} className="item px-1 text-xs">
              <summary className="cursor-pointer text-ink-faint hover:text-ink-dim">
                {item.text}
              </summary>
              <pre className="mt-1 rounded bg-base px-2 py-1 font-mono text-[10px] text-ink-faint">
                {item.detail}
              </pre>
            </details>
          );
        }
        if (item.kind === "result") {
          return (
            <div key={item.key} className="px-1 text-xs">
              <div className="flex items-baseline gap-2">
                <span className={item.ok ? "text-ok" : "text-danger"}>
                  {item.ok ? "✓" : "✕"}
                </span>
                <span className="min-w-0 flex-1 text-ink-dim">{item.text}</span>
              </div>
              {item.detail && (
                <pre className="mt-1 max-h-40 overflow-auto rounded bg-base px-2 py-1 font-mono text-[10px] text-ink-faint">
                  {item.detail}
                </pre>
              )}
            </div>
          );
        }
        const tone =
          item.kind === "error"
            ? "text-danger"
            : item.ok === false
              ? "text-attention"
              : "text-ok";
        return (
          <div key={item.key} className={`px-1 text-xs ${tone}`}>
            {item.text}
            {item.detail && (
              <span className="ml-1 text-ink-faint">— {item.detail}</span>
            )}
          </div>
        );
      })}

      {streaming && (
        <div className="agent-line rounded-r bg-agent/[0.07] py-2 pl-3 pr-2 text-xs leading-relaxed text-ink">
          {streaming}
          <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-agent align-middle" />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

function PlanPanel({ steps, currentStep }: { steps: PlanStep[]; currentStep: number | null }) {
  if (steps.length === 0) {
    return <p className="text-xs text-ink-faint">No plan yet — the agent is still thinking.</p>;
  }
  return (
    <ol className="space-y-3" data-testid="plan-list">
      {steps.map((step) => {
        const mark = STEP_MARKS[step.status];
        return (
          <li
            key={step.index}
            data-testid={`plan-step-${step.index}`}
            data-step-status={step.status}
            className={`flex gap-3 rounded px-2 py-1.5 ${
              step.index === currentStep ? "bg-raised" : ""
            }`}
          >
            <span className={`mt-px shrink-0 ${mark.className}`}>{mark.glyph}</span>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-ink">{step.description}</p>
              <p className="mt-0.5 font-mono text-[10px] text-ink-faint">
                {step.tool}
                {step.detail ? ` · ${step.detail}` : ""}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

interface Props {
  chat: ChatItem[];
  streaming: string;
  steps: PlanStep[];
  currentStep: number | null;
  /** Chunk labels from rag.retrieved -- what the agent read before planning. */
  retrieved: string[];
  diffs: Record<string, FileDiff>;
  pending: PendingApproval | null;
  trust: Record<string, TrustTier>;
  onApprove: (hunkIds: string[] | null) => void;
  onReject: () => void;
  onTrustToggle: (actionType: string, autoApprove: boolean) => void;
  srcFor: (path: string) => string;
  busy: boolean;
}

export function RightDock({
  chat,
  streaming,
  steps,
  currentStep,
  retrieved,
  diffs,
  pending,
  trust,
  onApprove,
  onReject,
  onTrustToggle,
  srcFor,
  busy,
}: Props) {
  const [tab, setTab] = useState<Tab>("chat");
  const diffList = Object.values(diffs);

  // An approval is the one thing that must never be buried behind a tab.
  useEffect(() => {
    if (pending) setTab("chat");
  }, [pending?.action.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "chat", label: "Chat" },
    { id: "plan", label: "Plan", badge: steps.length || undefined },
    { id: "graph", label: "Graph" },
    { id: "diffs", label: "Diffs", badge: diffList.length || undefined },
    { id: "trust", label: "Trust" },
  ];

  return (
    // Full width below `lg`. On a phone this is the whole session view, and
    // that is the right trade: the approval decision, the plan and the diffs
    // are readable at 375px, an editor and a terminal are not.
    <aside className="flex h-full w-full shrink-0 flex-col border-l border-edge bg-surface lg:w-[26rem]">
      <div className="flex h-8 shrink-0 items-stretch border-b border-edge">
        {tabs.map((entry) => (
          <button
            key={entry.id}
            onClick={() => setTab(entry.id)}
            data-testid={`dock-tab-${entry.id}`}
            className={`flex items-center gap-1.5 px-4 text-xs ${
              tab === entry.id
                ? "border-b-2 border-ink text-ink"
                : "border-b-2 border-transparent text-ink-faint hover:text-ink-dim"
            }`}
          >
            {entry.label}
            {entry.badge !== undefined && (
              <span className="rounded bg-raised px-1 text-[10px] text-ink-faint">
                {entry.badge}
              </span>
            )}
            {entry.id === "chat" && pending && (
              <span className="h-1.5 w-1.5 rounded-full bg-attention pulse-attention" />
            )}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-3">
        {pending && (
          <ApprovalCard
            pending={pending}
            onApprove={onApprove}
            onReject={onReject}
            busy={busy}
          />
        )}

        {tab === "chat" && <ChatFeed items={chat} streaming={streaming} />}
        {tab === "plan" && <PlanPanel steps={steps} currentStep={currentStep} />}
        {tab === "graph" && (
          <CognitionPanel steps={steps} currentStep={currentStep} retrieved={retrieved} />
        )}
        {tab === "diffs" &&
          (diffList.length === 0 ? (
            <p className="text-xs text-ink-faint">No changes yet.</p>
          ) : (
            <div className="space-y-4" data-testid="diffs-panel">
              {diffList.map((diff) => (
                <DiffView key={diff.path} diff={diff} srcFor={srcFor} />
              ))}
            </div>
          ))}
        {tab === "trust" && (
          <TrustPanel tiers={trust} onToggle={onTrustToggle} busy={busy} />
        )}
      </div>
    </aside>
  );
}
