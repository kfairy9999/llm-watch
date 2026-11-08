"""Point any OpenAI-compatible client at the llm-watch proxy.

The proxy sets a User-Agent and retries upstream 429 / 503 responses, honoring
Retry-After. Start it with the Groq base URL:

    export GROQ_API_KEY=...
    python -m llmwatch proxy \
        --upstream https://api.groq.com/openai/v1 \
        --user-agent llm-watch-example/0.1.0 \
        --port 8787

Then point a client at the proxy instead of Groq:

    export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
    export OPENAI_API_KEY=$GROQ_API_KEY

This file is documentation you can run as a reminder. It does not send traffic.
"""

from __future__ import annotations


def main() -> int:
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
