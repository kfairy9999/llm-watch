from __future__ import annotations

import pytest

from llmwatch.pricing import load_price_table


@pytest.fixture
def price_table():
    return load_price_table()


def sample_call(**overrides):
    row = {
        "id": "call_test",
        "created_at": "2026-11-01T00:00:00Z",
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
        "endpoint": "/v1/chat/completions",
        "prompt": [{"role": "user", "content": "Hi"}],
        "response": {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]},
        "response_text": "Hello",
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "token_source": "provider",
        "latency_ms": 100.0,
        "cost_usd": 0.0,
        "price_source": "table",
        "status": "ok",
        "error_type": None,
        "error_message": None,
        "http_status": 200,
        "attempts": 1,
        "synthetic": False,
        "metadata": {"route": "support"},
        "streaming": False,
    }
    row.update(overrides)
    return row
