"""Model providers for the eval runner: checked-in fixtures, or Groq."""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from llmwatch.client import WatchClient
from llmwatch.eval.runner import Completion
from llmwatch.eval.suite import TestCase
from llmwatch.pricing import PriceTable
from llmwatch.text import estimate_tokens, render_messages, response_text

LATENCY_BANDS = {
    "llama-3.2-3b-preview": (90.0, 280.0),
    "llama-3.1-8b-instant": (180.0, 560.0),
    "llama-3.3-70b-versatile": (700.0, 1700.0),
}


def latency_for(model: str, rng: random.Random) -> float:
    low, high = LATENCY_BANDS.get(model, (200.0, 800.0))
    return round(math.exp(rng.uniform(math.log(low), math.log(high))), 2)


def fixture_completion_fn(
    fixtures: dict[str, dict[str, str]],
    *,
    simulate: bool = True,
    seed: int = 0,
):
    """Return scripted answers. Operational metrics are simulated when `simulate` is set."""
    rng = random.Random(seed)

    def complete(model: str, test: TestCase) -> str | Completion:
        try:
            text = fixtures[model][test.id]
        except KeyError as exc:
            raise KeyError(f"no scripted output for {model} / {test.id}") from exc
        if not simulate:
            return text
        prompt_tokens = estimate_tokens(render_messages(test.messages))
        completion_tokens = estimate_tokens(text)
        return Completion(
            text=text,
            latency_ms=latency_for(model, rng),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            metrics_simulated=True,
        )

    return complete


def groq_completion_fn(
    *,
    db_path: str | Path,
    api_key: str | None = None,
    price_table: PriceTable | None = None,
    user_agent: str = "llm-watch/0.1.0",
    max_retries: int = 4,
):
    """Live Groq chat completions. Requires GROQ_API_KEY. Not used by the test suite."""
    key = api_key or os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    client = WatchClient(
        base_url="https://api.groq.com/openai/v1",
        api_key=key,
        db_path=db_path,
        price_table=price_table,
        user_agent=user_agent,
        provider="groq",
        max_retries=max_retries,
    )

    def complete(model: str, test: TestCase) -> Completion:
        data = client.chat.completions.create(
            model=model,
            messages=test.messages,
            metadata={"suite": "eval", "test_id": test.id},
        )
        usage = data.get("usage") or {}
        return Completion(
            text=response_text(data),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            metrics_simulated=False,
        )

    return complete
