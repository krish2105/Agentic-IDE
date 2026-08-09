"""Token economics.

The meter already counted tokens; this turns that into money. Cost is the axis
developers actually budget against in 2026, and no IDE surfaces it well --
usually because the accounting lives in a billing dashboard three clicks away
from the thing that spent it.

The honesty rule matters here: an estimated token count must never be presented
as an exact cost. Every number carries whether it was measured or guessed.
"""

from __future__ import annotations

from sani_core.pricing import (
    PRICING,
    CostMeter,
    estimate_cost,
    price_for,
)


def test_a_known_model_resolves_to_its_published_rate():
    price = price_for("groq/llama-3.3-70b-versatile")
    assert price is not None
    assert price.input_per_mtok > 0
    assert price.output_per_mtok > 0


def test_an_unknown_model_has_no_price_rather_than_a_guessed_one():
    # Inventing a rate would put a confident wrong number in front of someone
    # making a budget decision. Absent is the honest answer.
    assert price_for("some-model-nobody-has-heard-of") is None


def test_model_lookup_ignores_provider_prefix_casing():
    assert price_for("GROQ/Llama-3.3-70B-Versatile") is not None


def test_cost_is_computed_per_million_tokens():
    price = price_for("openai/gpt-4o")
    assert price is not None
    cost = estimate_cost("openai/gpt-4o", input_tokens=1_000_000, output_tokens=0)
    assert cost == round(price.input_per_mtok, 6)


def test_input_and_output_are_priced_separately():
    # Output is materially more expensive than input on every major provider;
    # a meter that averaged them would understate the cost of a chatty agent.
    only_in = estimate_cost("openai/gpt-4o", input_tokens=1_000_000, output_tokens=0)
    only_out = estimate_cost("openai/gpt-4o", input_tokens=0, output_tokens=1_000_000)
    assert only_out > only_in


def test_cost_of_an_unpriced_model_is_none_not_zero():
    # Zero would read as "this was free", which is a different claim entirely.
    assert estimate_cost("mystery/model", input_tokens=5000, output_tokens=500) is None


def test_every_pricing_entry_is_well_formed():
    for name, price in PRICING.items():
        assert name == name.lower(), f"{name} must be stored lowercased for lookup"
        assert price.input_per_mtok >= 0
        assert price.output_per_mtok >= 0


# ---- the running meter -------------------------------------------------------


def test_the_meter_accumulates_across_steps():
    meter = CostMeter(model="openai/gpt-4o")
    meter.record(input_tokens=1000, output_tokens=200)
    meter.record(input_tokens=500, output_tokens=100)

    assert meter.input_tokens == 1500
    assert meter.output_tokens == 300
    assert meter.calls == 2


def test_the_meter_reports_a_total_cost_when_the_model_is_priced():
    meter = CostMeter(model="openai/gpt-4o")
    meter.record(input_tokens=1_000_000, output_tokens=0)
    snapshot = meter.to_dict()

    assert snapshot["total_usd"] is not None
    assert snapshot["total_usd"] > 0
    assert snapshot["priced"] is True


def test_the_meter_admits_when_it_cannot_price_a_model():
    meter = CostMeter(model="scripted")
    meter.record(input_tokens=1000, output_tokens=100)
    snapshot = meter.to_dict()

    assert snapshot["total_usd"] is None
    assert snapshot["priced"] is False
    # Tokens are still counted -- only the money is unknown.
    assert snapshot["input_tokens"] == 1000


def test_the_meter_marks_whether_counts_were_measured_or_estimated():
    measured = CostMeter(model="openai/gpt-4o")
    measured.record(input_tokens=10, output_tokens=2, estimated=False)
    assert measured.to_dict()["estimated"] is False

    # One estimated call taints the total: reporting a mixed figure as exact
    # would be the dishonest option.
    measured.record(input_tokens=10, output_tokens=2, estimated=True)
    assert measured.to_dict()["estimated"] is True


def test_a_fresh_meter_serialises_without_dividing_by_zero():
    snapshot = CostMeter(model="openai/gpt-4o").to_dict()
    assert snapshot["calls"] == 0
    assert snapshot["total_usd"] == 0.0
