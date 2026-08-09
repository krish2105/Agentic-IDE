import assert from "node:assert/strict";
import { test } from "node:test";
import { describeSpend, formatSpend } from "../src/pricing.ts";
import type { CostUsage } from "../src/types.ts";

function cost(over: Partial<CostUsage> = {}): CostUsage {
  return {
    model: "groq/llama-3.3-70b-versatile",
    input_tokens: 20,
    output_tokens: 14,
    total_tokens: 34,
    calls: 1,
    total_usd: 0.000025,
    priced: true,
    estimated: false,
    ...over,
  } as CostUsage;
}

test("an unpriced model reports tokens, never a price of zero", () => {
  // "$0.00" would be a claim that the run was free, which is a different and
  // wrong statement from "nobody publishes a rate for this model".
  const spend = formatSpend(cost({ total_usd: null, priced: false }));
  assert.equal(spend, "34 tok");
  assert.doesNotMatch(spend!, /\$/);
});

test("sub-cent spend is <$0.01, not a row of zeros", () => {
  // This is the drift being fixed: the web IDE said "$0.0000" and the extension
  // "<$0.01" for the same 0.000025.
  assert.equal(formatSpend(cost({ total_usd: 0.000025 })), "<$0.01");
  assert.equal(formatSpend(cost({ total_usd: 0.0099 })), "<$0.01");
});

test("a cent or more is shown to the cent", () => {
  assert.equal(formatSpend(cost({ total_usd: 0.01 })), "$0.01");
  assert.equal(formatSpend(cost({ total_usd: 1.239 })), "$1.24");
});

test("estimated token counts are flagged, never passed off as measured", () => {
  assert.equal(formatSpend(cost({ estimated: true, total_usd: 0.5 })), "~$0.50");
  assert.equal(formatSpend(cost({ estimated: true, total_usd: 0.000025 })), "~<$0.01");
});

test("a genuine zero is allowed to say zero", () => {
  // Distinct from unpriced: the rate is known and nothing was spent yet.
  assert.equal(formatSpend(cost({ total_usd: 0 })), "$0.00");
});

test("nothing is shown before the first call", () => {
  assert.equal(formatSpend(cost({ calls: 0 })), null);
  assert.equal(formatSpend(null), null);
  assert.equal(formatSpend(undefined), null);
  assert.equal(describeSpend(cost({ calls: 0 })), null);
});

test("the hover text says where the number came from", () => {
  assert.match(describeSpend(cost())!, /20 in \/ 14 out over 1 call/);
  assert.match(describeSpend(cost({ estimated: true }))!, /estimated/);
  assert.match(describeSpend(cost({ total_usd: null, priced: false }))!, /No published rate/);
});
