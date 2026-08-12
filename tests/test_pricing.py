import pytest
from app.services.pricing import (
    calculate_token_cost_cents,
    calculate_api_call_cost_cents,
    PRICE_INPUT_MICRO_CENTS_PER_TOKEN,
    PRICE_CACHED_INPUT_MICRO_CENTS_PER_TOKEN,
    PRICE_OUTPUT_MICRO_CENTS_PER_TOKEN,
)


def test_pure_input_tokens():
    # 1,000,000 input tokens * 30 micro-cents/token = 30,000,000 micro-cents = 30 cents ($0.30)
    assert calculate_token_cost_cents(1_000_000, 0, 0, 0) == 30


def test_pure_output_tokens():
    # 1,000,000 output tokens * 250 micro-cents/token = 250,000,000 micro-cents = 250 cents ($2.50)
    assert calculate_token_cost_cents(0, 0, 1_000_000, 0) == 250


def test_cached_input_is_cheaper_than_fresh_input():
    fresh = calculate_token_cost_cents(1_000_000, 0, 0, 0)
    cached = calculate_token_cost_cents(0, 1_000_000, 0, 0)
    assert cached < fresh
    assert PRICE_CACHED_INPUT_MICRO_CENTS_PER_TOKEN < PRICE_INPUT_MICRO_CENTS_PER_TOKEN


def test_reasoning_tokens_priced_as_output_not_separately():
    # reasoning tokens folded into the output bucket -- same total as if
    # they'd been submitted as plain output tokens.
    as_reasoning = calculate_token_cost_cents(0, 0, 0, 500_000)
    as_output = calculate_token_cost_cents(0, 0, 500_000, 0)
    assert as_reasoning == as_output


def test_categories_are_not_simply_summed_at_one_price():
    # If categories were wrongly summed and priced as one flat rate, this
    # would NOT match the per-category calculation below.
    input_t, cached_t, output_t, reasoning_t = 100_000, 50_000, 20_000, 5_000
    result = calculate_token_cost_cents(input_t, cached_t, output_t, reasoning_t)

    expected_micro_cents = (
        input_t * PRICE_INPUT_MICRO_CENTS_PER_TOKEN
        + cached_t * PRICE_CACHED_INPUT_MICRO_CENTS_PER_TOKEN
        + (output_t + reasoning_t) * PRICE_OUTPUT_MICRO_CENTS_PER_TOKEN
    )
    expected_cents = (expected_micro_cents + 500_000) // 1_000_000
    assert result == expected_cents


def test_zero_usage_costs_zero():
    assert calculate_token_cost_cents(0, 0, 0, 0) == 0
    assert calculate_api_call_cost_cents(0) == 0


def test_negative_tokens_rejected():
    with pytest.raises(ValueError):
        calculate_token_cost_cents(-1, 0, 0, 0)


def test_api_call_cost_is_integer_cents():
    result = calculate_api_call_cost_cents(250)
    assert isinstance(result, int)
    assert result == 250  # PRICE_PER_API_CALL_CENTS = 1 cent/call


def test_pinned_realistic_scenario():
    """A realistic single chat turn: 2000 input, 500 cached-input reused
    from a system prompt, 300 output, 150 hidden reasoning tokens."""
    result = calculate_token_cost_cents(
        input_tokens=2000, cached_input_tokens=500, output_tokens=300, reasoning_tokens=150
    )
    # input: 2000*30=60,000 | cached: 500*7=3,500 | output+reasoning: 450*250=112,500
    # total = 176,000 micro-cents -> rounds to 0 cents (less than half a cent)
    assert result == 0
