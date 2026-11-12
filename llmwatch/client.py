"""Drop-in client and wrapper for OpenAI-compatible chat completions."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from llmwatch.errors import WatchError, WatchProviderError
from llmwatch.pricing import PriceTable, load_price_table
from llmwatch.record import assemble_call, provider_error_message
from llmwatch.retry import send_with_retries
from llmwatch.store import open_store
from llmwatch.text import coerce_response

DEFAULT_USER_AGENT = "llm-watch/0.1.0"


class Completions:
    def __init__(self, client: WatchClient):
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict | None = None,
        **extra: Any,
    ) -> dict:
        if extra.get("stream"):
            raise WatchError(
                "WatchClient logs non-streaming chat completions. "
                "Leave stream unset, or point the client at the llm-watch HTTP proxy."
            )
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(extra)
        return self._client.complete(payload, metadata=metadata)


class Chat:
    def __init__(self, client: WatchClient):
        self.completions = Completions(client)


class WatchClient:
    """Small OpenAI-compatible chat client that writes every call to the ledger.

    The ledger is the SQLite file at ``db_path`` unless ``LLMWATCH_MONGODB_URI``
    is set. Retries 429 and 503. A Retry-After header, delta-seconds or HTTP-date,
    wins over exponential backoff. The configured User-Agent is sent on every attempt.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        db_path: str | Path,
        price_table: PriceTable | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        provider: str = "openai-compatible",
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_cap: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        synthetic: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_agent = user_agent
        self.provider = provider
        self.max_retries = max_retries
        self.retry_cap = retry_cap
        self.sleep = sleep
        self.rng = rng or random.Random()
        self.synthetic = synthetic
        self.price_table = price_table or load_price_table()
        self.store = open_store(db_path)
        self.store.migrate()
        self.chat = Chat(self)
        self._http = httpx.Client(transport=transport, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WatchClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def complete(self, payload: dict[str, Any], *, metadata: dict | None = None) -> dict:
        model = str(payload.get("model") or "")
        messages = list(payload.get("messages") or [])
        if not model:
            raise WatchError("chat completion requires a model")
        url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        started = time.perf_counter()

        def send() -> httpx.Response:
            return self._http.post(url, headers=headers, json=payload)

        try:
            response, attempts = send_with_retries(
                send,
                max_retries=self.max_retries,
                sleep=self.sleep,
                cap=self.retry_cap,
                rng=self.rng,
            )
        except httpx.TimeoutException as exc:
            call_id = self._record_transport_error(
                model=model,
                messages=messages,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_type="timeout",
                message="Timed out waiting for the provider.",
                metadata=metadata,
                attempts=1,
            )
            raise WatchProviderError(
                f"timed out waiting for the provider (call {call_id})",
                call_id=call_id,
            ) from exc
        except httpx.HTTPError as exc:
            call_id = self._record_transport_error(
                model=model,
                messages=messages,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_type="connection",
                message=str(exc)[:500],
                metadata=metadata,
                attempts=1,
            )
            raise WatchProviderError(f"connection failed (call {call_id})", call_id=call_id) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        body_text = response.text
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if response.status_code >= 400 or not isinstance(parsed, dict):
            message = provider_error_message(body_text, parsed)
            error_type = "rate_limit" if response.status_code == 429 else "http_error"
            call_id = self.store.insert_call(
                assemble_call(
                    price_table=self.price_table,
                    model=model,
                    messages=messages,
                    status="error",
                    latency_ms=latency_ms,
                    provider=self.provider,
                    attempts=attempts,
                    response=parsed if isinstance(parsed, dict) else None,
                    response_body_text=message,
                    http_status=response.status_code,
                    error_type=error_type,
                    error_message=message or f"HTTP {response.status_code}",
                    metadata=metadata,
                    synthetic=self.synthetic,
                )
            )
            raise WatchProviderError(
                f"provider returned {response.status_code} (call {call_id})",
                call_id=call_id,
                status_code=response.status_code,
            )
        self.store.insert_call(
            assemble_call(
                price_table=self.price_table,
                model=model,
                messages=messages,
                status="ok",
                latency_ms=latency_ms,
                provider=self.provider,
                attempts=attempts,
                response=parsed,
                http_status=response.status_code,
                metadata=metadata,
                synthetic=self.synthetic,
            )
        )
        return parsed

    def _record_transport_error(
        self,
        *,
        model: str,
        messages: list[dict],
        latency_ms: float,
        error_type: str,
        message: str,
        metadata: dict | None,
        attempts: int,
    ) -> str:
        return self.store.insert_call(
            assemble_call(
                price_table=self.price_table,
                model=model,
                messages=messages,
                status="error",
                latency_ms=latency_ms,
                provider=self.provider,
                attempts=attempts,
                error_type=error_type,
                error_message=message,
                metadata=metadata,
                synthetic=self.synthetic,
            )
        )


def watch(
    client: Any,
    *,
    db_path: str | Path,
    price_table: PriceTable | None = None,
    provider: str = "openai-sdk",
    metadata: dict | None = None,
    synthetic: bool = False,
) -> Any:
    """Patch `client.chat.completions.create` so each call is written to the ledger.

    Works with the official OpenAI SDK or any object that returns a dict or a
    pydantic model from `chat.completions.create`. The original response object
    is returned unchanged.
    """
    table = price_table or load_price_table()
    store = open_store(db_path)
    store.migrate()
    original = client.chat.completions.create
    base_metadata = dict(metadata or {})

    def create(*args: Any, **kwargs: Any) -> Any:
        request_model = str(kwargs.get("model") or (args[0] if args else "") or "")
        messages = list(kwargs.get("messages") or [])
        started = time.perf_counter()
        try:
            response = original(*args, **kwargs)
        except Exception as exc:
            store.insert_call(
                assemble_call(
                    price_table=table,
                    model=request_model or "unknown",
                    messages=messages,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    provider=provider,
                    attempts=1,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                    metadata=base_metadata,
                    synthetic=synthetic,
                )
            )
            raise
        data = coerce_response(response)
        store.insert_call(
            assemble_call(
                price_table=table,
                model=request_model or str(data.get("model") or "unknown"),
                messages=messages,
                status="ok",
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=provider,
                attempts=1,
                response=data,
                http_status=200,
                metadata=base_metadata,
                synthetic=synthetic,
            )
        )
        return response

    client.chat.completions.create = create
    return client
