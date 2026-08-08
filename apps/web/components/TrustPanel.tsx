"use client";

import type { TrustTier } from "@sani/client";

/**
 * The trust ladder, made visible (spec Section 5, Phase 4).
 *
 * Autonomy the user cannot see is indistinguishable from autonomy they did not
 * consent to. This panel is the answer to "what is it allowed to do without
 * asking me" -- including the tiers it will never be allowed, which are shown
 * locked rather than hidden, so the guarantee is legible rather than implied.
 */
export function TrustPanel({
  tiers,
  onToggle,
  busy,
}: {
  tiers: Record<string, TrustTier>;
  onToggle: (actionType: string, autoApprove: boolean) => void;
  busy: boolean;
}) {
  const entries = Object.values(tiers);
  const locked = entries.filter((tier) => tier.always_confirm);
  const earnable = entries.filter((tier) => !tier.always_confirm);

  return (
    <div className="space-y-5" data-testid="trust-panel">
      <section>
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
          Earns trust
        </h3>
        <ul className="space-y-1.5">
          {earnable.map((tier) => (
            <li
              key={tier.action_type}
              data-testid={`trust-${tier.action_type}`}
              data-auto={tier.auto_approve}
              className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-raised/60"
            >
              <button
                onClick={() => onToggle(tier.action_type, !tier.auto_approve)}
                disabled={busy}
                aria-label={`Toggle auto-approve for ${tier.action_type}`}
                className={`h-3.5 w-6 shrink-0 rounded-full transition ${
                  tier.auto_approve ? "bg-ok/70" : "bg-edge-strong"
                } disabled:opacity-40`}
              >
                <span
                  className={`block h-2.5 w-2.5 rounded-full bg-ink transition ${
                    tier.auto_approve ? "translate-x-3" : "translate-x-0.5"
                  }`}
                />
              </button>
              <code className="flex-1 truncate font-mono text-[11px] text-ink-dim">
                {tier.action_type}
              </code>
              {!tier.auto_approve && tier.consecutive_approvals > 0 && (
                <span
                  className="shrink-0 font-mono text-[10px] text-ink-faint"
                  title="Consecutive manual approvals before this earns autonomy"
                >
                  {tier.consecutive_approvals}/{tier.promotion_threshold}
                </span>
              )}
              {tier.auto_approve && (
                <span className="shrink-0 text-[10px] text-ok">auto</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
          Always asks
        </h3>
        <p className="mb-2 text-[11px] leading-relaxed text-ink-faint">
          Irreversible or high-blast-radius. These cannot be switched on at any
          trust level, and the server refuses the request if a client tries.
        </p>
        <ul className="space-y-1">
          {locked.map((tier) => (
            <li
              key={tier.action_type}
              data-testid={`trust-${tier.action_type}`}
              data-locked="true"
              className="flex items-center gap-2 px-2 py-1"
            >
              <span className="text-[11px] text-attention" aria-hidden>
                ⏻
              </span>
              <code className="flex-1 truncate font-mono text-[11px] text-ink-dim">
                {tier.action_type}
              </code>
              <span className="shrink-0 text-[10px] text-attention">locked</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
