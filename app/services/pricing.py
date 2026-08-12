"""
Cost calculation. Modeled on the "pinned constants + pinned tests" pattern
from FlyRank's chat-pricing.config.ts: prices live as named constants here,
never inline, so a pricing change is a one-line diff and every test that
depends on it fails loudly if the math ever drifts.

MONEY RULE: every intermediate and final money value is an integer.
- Token prices are stored in MICRO-CENTS PER TOKEN (1 micro-cent =
  1 / 1,000,000 of a cent) so that even a $0.15-per-million-token rate has
  an exact integer representation. We only round to whole cents once, at
  the very end of a calculation -- never mid-calculation. This is the same
  reason floats are banned for money: repeated rounding compounds error.

TOKEN CATEGORY RULES (the "genuinely tricky" part of this capstone):
1. Cached input tokens are billed at a separate, cheaper rate than fresh
   input tokens -- they are NOT the same bucket as input_tokens.
2. Reasoning tokens are billed at the OUTPUT rate, not a separate rate --
   they get added into the output bucket before pricing, not summed
   in afterward at their own price.
3. Categories are never simply summed as "total tokens x one price" --
   each bucket is priced independently, then the cent totals are summed.
"""

# Prices in micro-cents per token. Pinned; change here, tests catch drift.
PRICE_INPUT_MICRO_CENTS_PER_TOKEN = 30        # = $0.30 / 1M tokens
PRICE_CACHED_INPUT_MICRO_CENTS_PER_TOKEN = 7  # = $0.075 / 1M tokens (cheaper)
PRICE_OUTPUT_MICRO_CENTS_PER_TOKEN = 250      # = $2.50 / 1M tokens (reasoning counts here)

PRICE_PER_API_CALL_CENTS = 1  # flat $0.01 per metered API call, for rollup cost


def calculate_token_cost_cents(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
) -> int:
    """
    Returns the cost of one usage event's AI-token consumption, in whole
    cents (rounded, integer). Reasoning tokens are folded into the output
    bucket before pricing -- they are never priced as their own category.
    """
    if any(n < 0 for n in (input_tokens, cached_input_tokens, output_tokens, reasoning_tokens)):
        raise ValueError("token counts cannot be negative")

    billable_output_tokens = output_tokens + reasoning_tokens

    micro_cents = (
        input_tokens * PRICE_INPUT_MICRO_CENTS_PER_TOKEN
        + cached_input_tokens * PRICE_CACHED_INPUT_MICRO_CENTS_PER_TOKEN
        + billable_output_tokens * PRICE_OUTPUT_MICRO_CENTS_PER_TOKEN
    )

    # Round to nearest whole cent, once, at the end. Half-up rounding.
    cents = (micro_cents + 500_000) // 1_000_000
    return int(cents)


def calculate_api_call_cost_cents(call_count: int) -> int:
    if call_count < 0:
        raise ValueError("call_count cannot be negative")
    return call_count * PRICE_PER_API_CALL_CENTS
