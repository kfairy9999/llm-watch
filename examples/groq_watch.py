"""Record one live Groq chat completion.

Set GROQ_API_KEY. The test suite does not call Groq; it injects a mock transport
into build_client() and checks the User-Agent plus 429 / Retry-After handling.

    export GROQ_API_KEY=...
    python examples/groq_watch.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

from llmwatch.client import WatchClient


def build_client(**overrides: Any) -> WatchClient:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    kwargs: dict[str, Any] = dict(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        user_agent="llm-watch-example/0.1.0",
        max_retries=4,
        provider="groq",
        db_path=os.environ.get("LLMWATCH_DB", "data/llmwatch.db"),
    )
    kwargs.update(overrides)
    return WatchClient(**kwargs)


def main() -> int:
    if not os.environ.get("GROQ_API_KEY"):
        print("Set GROQ_API_KEY to call Groq. The test suite does not need this.", file=sys.stderr)
        return 2
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    with build_client() as client:
        data = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        )
    text = data["choices"][0]["message"]["content"]
    print(text)
    print("Recorded one live call. It is not part of the synthetic demo set.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
