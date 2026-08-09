"use client";

import type { PlanStep, StepStatus } from "@sani/client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useAppearance } from "@/components/system/ThemeProvider";
import { allows3D } from "@/lib/quality";

const CognitionGraph = dynamic(() => import("@/components/three/CognitionGraph"), {
  ssr: false,
  loading: () => <div className="skeleton h-[300px] rounded-xl" />,
});

interface Props {
  steps: PlanStep[];
  currentStep: number | null;
  retrieved: string[];
}

const STATUS_DOT: Record<StepStatus, string> = {
  pending: "bg-ink-faint",
  running: "bg-agent",
  complete: "bg-ok",
  rejected: "bg-attention",
  failed: "bg-danger",
  skipped: "bg-ink-faint",
};

/**
 * Flat rendering of the same graph.
 *
 * Not a consolation prize: this is what every reduced-motion user, every weak
 * GPU and every `off` tier sees, so it has to carry the same information --
 * the spine, the status, and crucially the retrieval that fed the plan.
 */
function CognitionFlat({ steps, currentStep, retrieved }: Props) {
  return (
    <div className="rounded-xl border border-edge bg-base/40 p-3" data-testid="cognition-flat">
      {retrieved.length > 0 && (
        <div className="mb-3 border-b border-edge pb-3">
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
            Read before planning
          </p>
          <ul className="space-y-0.5">
            {retrieved.map((label) => (
              <li key={label} className="truncate font-mono text-[11px] text-agent">
                {label}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ol className="space-y-2">
        {steps.map((step) => (
          <li key={step.index} className="flex items-start gap-2.5">
            <span className="mt-1.5 flex flex-col items-center gap-1">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[step.status]} ${
                  step.status === "running" ? "pulse-attention" : ""
                }`}
              />
              {step.index < steps.length - 1 && (
                <span className="h-5 w-px bg-edge-strong" />
              )}
            </span>
            <div
              className={`min-w-0 flex-1 rounded-lg px-2 py-1 ${
                step.index === currentStep ? "bg-raised" : ""
              }`}
            >
              <p className="text-xs leading-snug text-ink">{step.description}</p>
              <p className="mt-0.5 font-mono text-[10px] text-ink-faint">
                {step.tool} · {step.status}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Picks the 3D graph or the flat one from the quality tier, and pauses the
 * render loop whenever the document is hidden.
 */
export function CognitionPanel({ steps, currentStep, retrieved }: Props) {
  const { quality } = useAppearance();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  if (steps.length === 0) {
    return (
      <p className="text-xs text-ink-faint">
        No plan yet — the agent is still thinking.
      </p>
    );
  }

  if (!allows3D(quality)) {
    return <CognitionFlat steps={steps} currentStep={currentStep} retrieved={retrieved} />;
  }

  return (
    <div className="space-y-2">
      <CognitionGraph
        steps={steps}
        currentStep={currentStep}
        retrieved={retrieved}
        active={visible}
      />
      <p className="text-center font-mono text-[10px] uppercase tracking-wider text-ink-faint">
        {retrieved.length > 0
          ? "violet beams = code read before planning · glow = running"
          : "glow = running · hover a node for detail"}
      </p>
      {/* The graph is a visualisation, not the record. */}
      <div className="sr-only">
        <CognitionFlat steps={steps} currentStep={currentStep} retrieved={retrieved} />
      </div>
    </div>
  );
}
