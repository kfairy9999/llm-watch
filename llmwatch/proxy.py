"""HTTP proxy that forwards an OpenAI-compatible base URL and logs chat completions."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from llmwatch.pricing import PriceTable, load_price_table
from llmwatch.record import assemble_call, provider_error_message
from llmwatch.retry import send_with_retries
from llmwatch.store import Ledger, open_store
from llmwatch.text import response_text, sse_content

HOP_HEADERS = {"host", "content-length", "authorization", "user-agent", "connection", "transfer-encoding"}


@dataclass
class ForwardResult:
    status_code: int
    body: bytes
    media_type: str


def join_upstream(upstream: str, path: str) -> str:
    """Join a base URL that already includes `/v1` with the proxy's relative path.

    A client pointed at `http://proxy/v1` requests `/v1/chat/completions`. The
    upstream base is `https://host/openai/v1`, so the forwarded path is
    `chat/completions`.
    """
    relative = path.lstrip("/")
    if relative.startswith("v1/"):
        relative = relative[3:]
    return upstream.rstrip("/") + "/" + relative


def create_proxy_app(
    *,
    upstream: str,
    db_path: str | Path,
    user_agent: str = "llm-watch/0.1.0",
    api_key: str | None = None,
    price_table: PriceTable | None = None,
    provider: str = "openai-compatible",
    max_retries: int = 2,
    retry_cap: float = 60.0,
    timeout: float = 60.0,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> FastAPI:
    table = price_table or load_price_table()
    store = open_store(db_path)
    store.migrate()
    http = httpx.Client(transport=transport, timeout=timeout)
    app = FastAPI(title="llm-watch proxy")
    app.state.http = http

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def handle(full_path: str, request: Request) -> Response:
        body = await request.body()
        result = forward_request(
            method=request.method,
            path=full_path,
            query=request.url.query,
            body=body,
            incoming_headers=dict(request.headers),
            upstream=upstream,
            http=http,
            store=store,
            user_agent=user_agent,
            api_key=api_key,
            price_table=table,
            provider=provider,
            max_retries=max_retries,
            retry_cap=retry_cap,
            sleep=sleep,
            rng=rng or random.Random(),
        )
        return Response(content=result.body, status_code=result.status_code, media_type=result.media_type)

    return app


def forward_request(
    *,
    method: str,
    path: str,
    query: str,
    body: bytes,
    incoming_headers: dict[str, str],
    upstream: str,
    http: httpx.Client,
    store: Ledger,
    user_agent: str,
    api_key: str | None,
    price_table: PriceTable,
    provider: str,
    max_retries: int,
    retry_cap: float,
    sleep: Callable[[float], None],
    rng: random.Random,
) -> ForwardResult:
    url = join_upstream(upstream, path)
    if query:
        url = f"{url}?{query}"
    headers = _outgoing_headers(incoming_headers, user_agent=user_agent, api_key=api_key)
    record = method.upper() == "POST" and path.rstrip("/").endswith("chat/completions")
    payload = _json_or_none(body) if record else None
    streaming = bool(isinstance(payload, dict) and payload.get("stream"))
    started = time.perf_counter()

    def send() -> httpx.Response:
        return http.request(method, url, headers=headers, content=body)

    response, attempts = send_with_retries(
        send,
        max_retries=max_retries if record else 0,
        sleep=sleep,
        cap=retry_cap,
        rng=rng,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    media_type = response.headers.get("content-type", "application/json")
    if record and isinstance(payload, dict):
        _record_proxy_exchange(
            store=store,
            price_table=price_table,
            provider=provider,
            payload=payload,
            response=response,
            latency_ms=latency_ms,
            attempts=attempts,
            streaming=streaming,
        )
    return ForwardResult(status_code=response.status_code, body=response.content, media_type=media_type.split(";")[0])


def _outgoing_headers(incoming: dict[str, str], *, user_agent: str, api_key: str | None) -> dict[str, str]:
    headers = {key: value for key, value in incoming.items() if key.lower() not in HOP_HEADERS}
    headers["User-Agent"] = user_agent
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif "authorization" in {key.lower() for key in incoming}:
        for key, value in incoming.items():
            if key.lower() == "authorization":
                headers["Authorization"] = value
                break
    headers.setdefault("Content-Type", "application/json")
    return headers


def _json_or_none(body: bytes) -> dict | None:
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _record_proxy_exchange(
    *,
    store: Ledger,
    price_table: PriceTable,
    provider: str,
    payload: dict,
    response: httpx.Response,
    latency_ms: float,
    attempts: int,
    streaming: bool,
) -> None:
    messages = payload.get("messages") or []
    model = str(payload.get("model") or "unknown")
    parsed = _json_or_none(response.content)
    text = ""
    token_override = None
    if streaming:
        text, usage = sse_content(response.text)
        if usage and usage.get("prompt_tokens") is not None:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            token_override = (
                prompt_tokens,
                completion_tokens,
                int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
                "provider",
            )
        response_obj = parsed
    else:
        response_obj = parsed
        text = ""
    if response.status_code >= 400 or (not streaming and not isinstance(parsed, dict)):
        message = provider_error_message(response.text, parsed)
        store.insert_call(
            assemble_call(
                price_table=price_table,
                model=model,
                messages=messages,
                status="error",
                latency_ms=latency_ms,
                provider=provider,
                attempts=attempts,
                response=parsed,
                response_body_text=message,
                http_status=response.status_code,
                error_type="rate_limit" if response.status_code == 429 else "http_error",
                error_message=message or f"HTTP {response.status_code}",
                streaming=streaming,
            )
        )
        return
    if streaming and token_override is None and text:
        response_obj = {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}}],
        }
    row = assemble_call(
        price_table=price_table,
        model=model,
        messages=messages,
        status="ok",
        latency_ms=latency_ms,
        provider=provider,
        attempts=attempts,
        response=response_obj if isinstance(response_obj, dict) else None,
        response_body_text=text,
        http_status=response.status_code,
        streaming=streaming,
        token_override=token_override,
    )
    if streaming and not row["response_text"]:
        row["response_text"] = text or response_text(response_obj if isinstance(response_obj, dict) else None)
    store.insert_call(row)
