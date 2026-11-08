"""Small text helpers shared by the ledger, scorers, and seed data."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def estimate_tokens(text: str) -> int:
    """Rough stand-in for a tokenizer: about four characters per token.

    Callers must label these counts as estimates. They are not provider usage.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def render_messages(messages: list[dict] | None) -> str:
    parts: list[str] = []
    for message in messages or []:
        role = str(message.get("role", "user"))
        parts.append(f"{role}: {content_to_text(message.get('content'))}")
    return "\n".join(parts)


def user_text(messages: list[dict] | None) -> str:
    chunks: list[str] = []
    for message in messages or []:
        if message.get("role") == "user":
            chunks.append(content_to_text(message.get("content")))
    if chunks:
        return "\n\n".join(chunks)
    return render_messages(messages)


def coerce_response(response: Any) -> dict:
    """Normalize an OpenAI SDK object or a plain dict into a JSON object."""
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(response, "to_dict"):
        dumped = response.to_dict()
        if isinstance(dumped, dict):
            return dumped
    raise TypeError("chat response is not a dict or an OpenAI-style model")


def response_text(data: dict | None) -> str:
    if not data:
        return ""
    choices = data.get("choices") or []
    if not choices or not isinstance(choices, list):
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    if message:
        return content_to_text(message.get("content"))
    return ""


def preview(text: str, limit: int = 140) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def extract_json(text: str) -> str:
    """Pull a JSON value out of a raw reply or a fenced block."""
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, flags=re.S | re.I)
    if fenced:
        return fenced.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    start_obj = stripped.find("{")
    start_arr = stripped.find("[")
    starts = [index for index in (start_obj, start_arr) if index >= 0]
    if not starts:
        return stripped
    start = min(starts)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if end > start:
        return stripped[start : end + 1]
    return stripped


def sse_content(body: str) -> tuple[str, dict | None]:
    """Collect streamed assistant text and the last usage object, if any."""
    parts: list[str] = []
    usage: dict | None = None
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            message = choice.get("message") or {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                parts.append(message["content"])
    return "".join(parts), usage
