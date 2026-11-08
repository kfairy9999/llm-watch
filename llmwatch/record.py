"""Build one ledger row from a chat-completions exchange."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from llmwatch.pricing import PriceTable
from llmwatch.text import estimate_tokens, new_id, render_messages, response_text


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def token_usage(data: dict | None, messages: list[dict], text: str) -> tuple[int, int, int, str]:
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict) and usage.get("prompt_tokens") is not None:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        return prompt_tokens, completion_tokens, total, "provider"
    prompt_tokens = estimate_tokens(render_messages(messages))
    completion_tokens = estimate_tokens(text)
    return prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, "estimate"


def provider_error_message(body: str, payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
    return (body or "")[:500]


def assemble_call(
    *,
    price_table: PriceTable,
    model: str,
    messages: list[dict],
    status: str,
    latency_ms: float,
    provider: str,
    attempts: int,
    response: dict | None = None,
    response_body_text: str = "",
    http_status: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
    synthetic: bool = False,
    streaming: bool = False,
    endpoint: str = "/v1/chat/completions",
    created_at: str | None = None,
    call_id: str | None = None,
    token_override: tuple[int, int, int, str] | None = None,
) -> dict[str, Any]:
    text = response_text(response) if response else response_body_text
    if token_override is not None:
        prompt_tokens, completion_tokens, total_tokens, token_source = token_override
    elif status == "ok":
        prompt_tokens, completion_tokens, total_tokens, token_source = token_usage(response, messages, text)
    else:
        prompt_tokens, completion_tokens, total_tokens, token_source = 0, 0, 0, "none"
    if status == "ok":
        cost, price_source = price_table.compute_cost(model, prompt_tokens, completion_tokens)
    else:
        cost, price_source = 0.0, price_table.resolve(model)[1]
    meta = dict(metadata or {})
    response_model = (response or {}).get("model") if response else None
    if response_model and response_model != model:
        meta["response_model"] = response_model
    return {
        "id": call_id or new_id("call"),
        "created_at": created_at or utc_now(),
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "prompt": messages,
        "response": response,
        "response_text": text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "token_source": token_source,
        "latency_ms": round(latency_ms, 3),
        "cost_usd": cost,
        "price_source": price_source,
        "status": status,
        "error_type": error_type,
        "error_message": error_message,
        "http_status": http_status,
        "attempts": attempts,
        "synthetic": synthetic,
        "metadata": meta,
        "streaming": streaming,
    }
