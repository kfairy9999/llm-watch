from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from groq_watch import build_client, main as groq_main
from llmwatch.client import WatchClient, watch
from llmwatch.errors import WatchError, WatchProviderError
from llmwatch.proxy import create_proxy_app, join_upstream
from llmwatch.store import Store
from llmwatch.text import estimate_tokens, render_messages


def _completion(content: str, *, usage: dict | None = None, model: str = "llama-3.1-8b-instant") -> dict:
    body = {
        "id": "chatcmpl_test",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def test_client_records_usage_cost_user_agent_and_hides_the_key(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        seen["auth"] = request.headers["authorization"]
        assert request.url == "https://api.groq.com/openai/v1/chat/completions"
        return httpx.Response(
            200,
            json=_completion("Paris", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
        )

    client = WatchClient(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        db_path=tmp_path / "t.db",
        user_agent="llm-watch-test/0",
        provider="groq",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    out = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Hi"}],
        metadata={"route": "support"},
    )
    client.close()
    assert out["choices"][0]["message"]["content"] == "Paris"
    row = Store(tmp_path / "t.db").get_call(Store(tmp_path / "t.db").list_calls()[1][0]["id"])
    assert row["prompt_tokens"] == 10
    assert row["token_source"] == "provider"
    assert row["cost_usd"] == pytest.approx((10 * 0.05 + 2 * 0.08) / 1_000_000)
    assert row["metadata"]["route"] == "support"
    assert row["synthetic"] is False
    assert seen["ua"] == "llm-watch-test/0"
    assert seen["auth"] == "Bearer secret-key"
    assert b"secret-key" not in (tmp_path / "t.db").read_bytes()


def test_missing_usage_is_an_estimate(tmp_path):
    messages = [{"role": "user", "content": "Hi"}]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("Hello"))

    client = WatchClient(
        base_url="https://example.test/v1",
        api_key="k",
        db_path=tmp_path / "t.db",
        transport=httpx.MockTransport(handler),
    )
    client.chat.completions.create(model="llama-3.1-8b-instant", messages=messages)
    client.close()
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    assert row["token_source"] == "estimate"
    assert row["prompt_tokens"] == estimate_tokens(render_messages(messages))
    assert row["completion_tokens"] == estimate_tokens("Hello")


def test_429_retries_then_records_one_success(tmp_path):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}})
        return httpx.Response(
            200,
            json=_completion("ok", usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
        )

    sleeps: list[float] = []
    client = WatchClient(
        base_url="https://example.test/v1",
        api_key="k",
        db_path=tmp_path / "t.db",
        max_retries=1,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": "Hi"}])
    client.close()
    _total, rows = Store(tmp_path / "t.db").list_calls()
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["attempts"] == 2
    assert sleeps == [0.0]


def test_exhausted_429_is_logged_and_raised(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}})

    client = WatchClient(
        base_url="https://example.test/v1",
        api_key="k",
        db_path=tmp_path / "t.db",
        max_retries=1,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    with pytest.raises(WatchProviderError) as caught:
        client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": "Hi"}])
    client.close()
    row = Store(tmp_path / "t.db").get_call(caught.value.call_id)
    assert row["status"] == "error"
    assert row["error_type"] == "rate_limit"
    assert row["attempts"] == 2
    assert row["http_status"] == 429


def test_timeout_is_logged(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = WatchClient(
        base_url="https://example.test/v1",
        api_key="k",
        db_path=tmp_path / "t.db",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(WatchProviderError):
        client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": "Hi"}])
    client.close()
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    assert row["error_type"] == "timeout"
    assert row["status"] == "error"


def test_streaming_is_rejected_before_the_network(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not send")

    client = WatchClient(
        base_url="https://example.test/v1",
        api_key="k",
        db_path=tmp_path / "t.db",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(WatchError):
        client.chat.completions.create(
            model="m",
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
        )
    client.close()


def test_watch_wraps_an_sdk_like_client(tmp_path):
    class Response:
        def model_dump(self):
            return _completion("wrapped", usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5})

    class Completions:
        def create(self, **kwargs):
            assert kwargs["model"] == "llama-3.3-70b-versatile"
            return Response()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Fake:
        def __init__(self):
            self.chat = Chat()

    fake = watch(Fake(), db_path=tmp_path / "t.db", provider="openai-sdk")
    returned = fake.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hi"}],
    )
    assert returned.model_dump()["choices"][0]["message"]["content"] == "wrapped"
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    assert row["model"] == "llama-3.3-70b-versatile"
    assert row["provider"] == "openai-sdk"
    assert row["token_source"] == "provider"
    assert row["cost_usd"] == pytest.approx((4 * 0.59 + 1 * 0.79) / 1_000_000)


def test_wrapper_records_provider_exceptions(tmp_path):
    class Completions:
        def create(self, **_kwargs):
            raise RuntimeError("boom")

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Fake:
        def __init__(self):
            self.chat = Chat()

    fake = watch(Fake(), db_path=tmp_path / "t.db")
    with pytest.raises(RuntimeError):
        fake.chat.completions.create(model="m", messages=[{"role": "user", "content": "Hi"}])
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    assert row["status"] == "error"
    assert row["error_type"] == "RuntimeError"


def test_groq_example_sends_user_agent_and_honors_retry_after(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow"}})
        return httpx.Response(
            200,
            json=_completion("pong", usage={"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9}),
        )

    client = build_client(
        db_path=tmp_path / "t.db",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    data = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
    )
    client.close()
    assert data["choices"][0]["message"]["content"] == "pong"
    assert len(calls) == 2
    for request in calls:
        assert request.headers["user-agent"] == "llm-watch-example/0.1.0"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.host == "api.groq.com"
        assert request.url.path == "/openai/v1/chat/completions"
    assert b"test-key" not in (tmp_path / "t.db").read_bytes()


def test_groq_example_main_exits_without_a_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq_main() == 2


def test_join_upstream_strips_duplicate_v1():
    assert (
        join_upstream("https://api.groq.com/openai/v1", "/v1/chat/completions")
        == "https://api.groq.com/openai/v1/chat/completions"
    )


def test_proxy_forwards_records_and_retries(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["user-agent"] == "llm-watch-proxy/test"
        assert request.headers["authorization"] == "Bearer upstream-key"
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json=_completion("proxied", usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}),
        )

    app = create_proxy_app(
        upstream="https://api.groq.com/openai/v1",
        db_path=tmp_path / "t.db",
        user_agent="llm-watch-proxy/test",
        api_key="upstream-key",
        max_retries=1,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "proxied"
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    assert row["status"] == "ok"
    assert row["attempts"] == 2
    assert row["synthetic"] is False
    assert row["token_source"] == "provider"
    models = client.get("/v1/models")
    # The mock transport answers every path with the chat payload after the first 429.
    # A second logical request should not create another ledger row when it is not chat... 
    # The handler returns 200 JSON for any later call, including GET /v1/models.
    assert models.status_code == 200
    assert Store(tmp_path / "t.db").count_calls() == 1


def test_proxy_buffers_a_stream_and_keeps_the_sse_body(tmp_path):
    sse = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            'data: {"choices":[{"delta":{"content":"!"}}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}',
            "data: [DONE]",
            "",
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse)

    app = create_proxy_app(
        upstream="https://example.test/v1",
        db_path=tmp_path / "t.db",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
    )
    assert response.status_code == 200
    assert response.text == sse
    row = Store(tmp_path / "t.db").list_calls()[1][0]
    detail = Store(tmp_path / "t.db").get_call(row["id"])
    assert row["streaming"] is True
    assert detail["response_text"] == "Hi!"
    assert row["prompt_tokens"] == 4
    assert row["token_source"] == "provider"
    json.dumps(detail)
