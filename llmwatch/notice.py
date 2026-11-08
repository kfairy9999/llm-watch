"""Copy that must stay attached to synthetic demo data."""

from __future__ import annotations

__version__ = "0.1.0"

DEMO_DATASET = "synthetic-demo"
DEMO_FROZEN_AT = "2026-11-08T00:00:00Z"
DEMO_SEED = 20261108

SYNTHETIC_DISCLAIMER = (
    "Synthetic demo data. Not a live provider trace and not a benchmark result. "
    "Call traffic, timestamps, token counts, and latencies are simulated. "
    "Dollar amounts apply the bundled price table to those simulated tokens. "
    "Eval scores are the real runner grading scripted answers, so the dashboard works without an API key."
)

MIXED_DISCLAIMER = (
    "This ledger mixes synthetic demo rows with recorded calls. "
    "Synthetic rows are marked in the table. Do not treat aggregate charts as production traffic."
)

PRICE_NOTE = (
    "Illustrative USD per 1M tokens, not an invoice. "
    "Providers change prices; edit the price table before you rely on it."
)


def disclaimer_for(
    *,
    synthetic_calls: int,
    recorded_calls: int,
    synthetic_comparisons: int = 0,
    recorded_comparisons: int = 0,
) -> str | None:
    """Return the banner string for a ledger, or None when every row is recorded."""
    synthetic = synthetic_calls + synthetic_comparisons
    recorded = recorded_calls + recorded_comparisons
    if synthetic and recorded:
        return MIXED_DISCLAIMER
    if synthetic:
        return SYNTHETIC_DISCLAIMER
    return None
