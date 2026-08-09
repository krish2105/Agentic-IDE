/**
 * How spend is written, in one place.
 *
 * The web IDE rendered `~$0.0000` and the VS Code extension `~<$0.01` for the
 * same number. Both were "correct"; neither matched the other, and `$0.0000`
 * reads uncomfortably close to "this was free" -- which is the exact claim
 * `sani_core.pricing` refuses to make by returning null for an unpriced model.
 *
 * Two surfaces formatting one measurement by hand is the drift the
 * shared-client rule exists to stop, so the rules live here and both callers
 * ask rather than decide:
 *
 *   * No priced total -> fall back to the token count. Never "$0.00": absence of
 *     a rate is not evidence of being free.
 *   * Below a cent -> "<$0.01" rather than a string of zeros, because the
 *     leading digits are the only ones a reader takes anything from.
 *   * Estimated token counts -> "~", so a number derived from `len/4` never
 *     poses as measured.
 */

import type { CostUsage } from "./types.ts";

/** Below this, the exact figure carries no information a reader can use. */
const SUB_CENT = 0.01;

/**
 * The spend to show next to the token meter, or null when there is nothing
 * honest to say. Callers render null as "no spend shown" rather than zero.
 */
export function formatSpend(cost: CostUsage | null | undefined): string | null {
  if (!cost || cost.calls === 0) return null;

  const tilde = cost.estimated ? "~" : "";

  // An unpriced model still counted tokens, so say that instead of implying a
  // price of zero.
  if (cost.total_usd === null || cost.total_usd === undefined) {
    return `${cost.total_tokens.toLocaleString()} tok`;
  }

  if (cost.total_usd === 0) return `${tilde}$0.00`;
  if (cost.total_usd < SUB_CENT) return `${tilde}<$0.01`;
  return `${tilde}$${cost.total_usd.toFixed(2)}`;
}

/** The hover text behind that figure: where it came from, and how solid it is. */
export function describeSpend(cost: CostUsage | null | undefined): string | null {
  if (!cost || cost.calls === 0) return null;

  const calls = `${cost.calls} call${cost.calls === 1 ? "" : "s"}`;
  const model = cost.model ?? "an unknown model";

  if (cost.total_usd === null || cost.total_usd === undefined) {
    return `No published rate for ${model} — tokens counted, cost unknown. ${cost.total_tokens.toLocaleString()} tokens over ${calls}.`;
  }

  const basis = cost.estimated
    ? " Token counts are estimated, so this is approximate."
    : "";
  return `$${cost.total_usd.toFixed(6)} — ${cost.input_tokens.toLocaleString()} in / ${cost.output_tokens.toLocaleString()} out over ${calls} on ${model}.${basis}`;
}
