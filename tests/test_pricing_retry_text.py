from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from llmwatch.pricing import PriceTable, load_price_table
from llmwatch.retry import delay_for, parse_retry_after, send_with_retries
from llmwatch.text import estimate_tokens, extract_json, sse_content


def test_known_model_cost_and_unknown_default():
    table = load_price_table()
    cost, source = table.compute_cost("llama-3.1-8b-instant", 1_000_000, 1_000_000)
    assert source == "table"
    assert cost == pytest.approx(0.05 + 0.08)
    cost, source = table.compute_cost("no-such-model", 1_000_000, 2_000_000)
    assert source == "default"
    assert cost == pytest.approx(1.0 + 6.0)


def test_negative_price_rejected():
    with pytest.raises(ValueError):
        PriceTable.from_dict({"models": {}, "default": {"input": -1, "output": 1}})


def test_estimate_tokens_is_labeled_by_callers_via_formula():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 1
    assert estimate_tokens("a" * 8) == 2


def test_extract_json_from_fence_and_prose():
    assert extract_json('```json\n{"id": "TCK-1042"}\n```') == '{"id": "TCK-1042"}'
    assert extract_json('sure {"a": 1} thanks') == '{"a": 1}'


def test_sse_collects_deltas_and_usage():
    body = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            'data: {"choices":[{"delta":{"content":" there"}}],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
            "data: [DONE]",
        ]
    )
    text, usage = sse_content(body)
    assert text == "Hi there"
    assert usage["prompt_tokens"] == 3


def test_retry_after_seconds_and_http_date():
    assert parse_retry_after("1.5") == 1.5
    assert parse_retry_after("-2") is None
    assert parse_retry_after("nope") is None
    now = datetime(2015, 10, 21, 7, 28, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:10 GMT", now=now) == pytest.approx(10)


def test_delay_honors_header_and_cap():
    import random

    rng = random.Random(0)
    response = httpx.Response(429, headers={"retry-after": "1.5"})
    assert delay_for(response, attempt=3, cap=60, rng=rng) == 1.5
    huge = httpx.Response(429, headers={"retry-after": "120"})
    assert delay_for(huge, attempt=0, cap=8, rng=rng) == 8
    plain = httpx.Response(503)
    delay = delay_for(plain, attempt=0, cap=8, rng=rng, base=0.25)
    assert 0 <= delay <= 0.25


def test_send_with_retries_stops_on_success_and_does_not_retry_500():
    sleeps: list[float] = []
    statuses = [429, 200]

    def send() -> httpx.Response:
        code = statuses.pop(0)
        headers = {"retry-after": "0"} if code == 429 else {}
        return httpx.Response(code, headers=headers)

    response, attempts = send_with_retries(
        send,
        max_retries=2,
        sleep=sleeps.append,
        cap=60,
    )
    assert response.status_code == 200
    assert attempts == 2
    assert sleeps == [0]

    def once() -> httpx.Response:
        return httpx.Response(500)

    response, attempts = send_with_retries(once, max_retries=3, sleep=sleeps.append, cap=60)
    assert response.status_code == 500
    assert attempts == 1
