"""Token economics: what a session actually cost.

The context meter already counted tokens. This turns that into money, because
cost is the axis developers budget against and it usually lives in a billing
dashboard three clicks away from the thing that spent it.

One rule governs this module: **never present a guess as a measurement.** An
unpriced model reports `None`, not `0.0` -- zero would read as "this was free",
which is a different and wrong claim. A total built from any estimated token
count is flagged `estimated`, so a number nobody can stand behind is never
displayed as though someone can.

Rates are USD per million tokens, and they go stale. They are a planning aid,
not an invoice.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


#: Keys are lowercased for case-insensitive lookup. Deliberately a short list:
#: an entry here is a claim about someone's bill, so a model belongs in it only
#: when its rate is actually known.
PRICING: dict[str, ModelPrice] = {
    # Groq
    "groq/llama-3.3-70b-versatile": ModelPrice(0.59, 0.79),
    "groq/llama-3.1-8b-instant": ModelPrice(0.05, 0.08),
    # OpenAI
    "openai/gpt-4o": ModelPrice(2.50, 10.00),
    "openai/gpt-4o-mini": ModelPrice(0.15, 0.60),
    # Anthropic
    "anthropic/claude-3-5-sonnet-20241022": ModelPrice(3.00, 15.00),
    "anthropic/claude-3-5-haiku-20241022": ModelPrice(0.80, 4.00),
    # Google
    "gemini/gemini-2.0-flash": ModelPrice(0.10, 0.40),
}


def price_for(model: str | None) -> ModelPrice | None:
    """The published rate for a model, or ``None`` if we do not know it."""
    if not model:
        return None
    return PRICING.get(model.strip().lower())


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one call, or ``None`` when the model has no known rate."""
    price = price_for(model)
    if price is None:
        return None
    cost = (
        input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
    ) / 1_000_000
    return round(cost, 6)


@dataclass(slots=True)
class CostMeter:
    """Running spend for one session.

    Accumulates across steps so the status bar can show burn as it happens
    rather than a total that only exists once the run is over.
    """

    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    #: True once any recorded call used an approximated token count. One
    #: estimated call taints the total -- reporting a mixed figure as exact
    #: would be the dishonest option.
    estimated: bool = field(default=False)

    def record(
        self, input_tokens: int, output_tokens: int, *, estimated: bool = True
    ) -> None:
        self.input_tokens += max(0, input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.calls += 1
        if estimated:
            self.estimated = True

    @property
    def total_usd(self) -> float | None:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)

    @property
    def priced(self) -> bool:
        return price_for(self.model) is not None

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "calls": self.calls,
            "total_usd": self.total_usd,
            "priced": self.priced,
            "estimated": self.estimated,
        }
