"""Retry-After parsing and a small retry loop for 429 and 503."""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

RETRY_STATUSES = (429, 503)


def parse_retry_after(value: str, *, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header.

    The header is either a non-negative delta in seconds or an HTTP date.
    Returns None when the value is not a delay we can honor.
    """
    raw = value.strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    else:
        if math.isnan(seconds) or math.isinf(seconds) or seconds < 0:
            return None
        return seconds
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (when - current).total_seconds())


def delay_for(
    response: httpx.Response,
    *,
    attempt: int,
    cap: float,
    rng: random.Random,
    base: float = 0.25,
    now: datetime | None = None,
) -> float:
    """Seconds to wait before the next attempt.

    A parseable Retry-After is honored up to `cap`. Otherwise the wait is
    full-jitter exponential backoff, also capped. The cap exists so a huge
    header cannot stall the process; a real deployment should set it above
    the provider's normal cooldown.
    """
    header = response.headers.get("retry-after")
    if header:
        parsed = parse_retry_after(header, now=now)
        if parsed is not None:
            return min(cap, parsed)
    ceiling = min(cap, base * (2**attempt))
    if ceiling <= 0:
        return 0.0
    return rng.uniform(0, ceiling)


def send_with_retries(
    send: Callable[[], httpx.Response],
    *,
    max_retries: int,
    sleep: Callable[[float], None],
    cap: float,
    rng: random.Random | None = None,
    base: float = 0.25,
    now: datetime | None = None,
) -> tuple[httpx.Response, int]:
    """Send once, then retry 429 and 503 up to `max_retries` extra times.

    Returns the last response and the number of attempts that were made.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    random_source = rng or random.Random()
    for attempt in range(max_retries + 1):
        response = send()
        if response.status_code not in RETRY_STATUSES or attempt == max_retries:
            return response, attempt + 1
        sleep(
            delay_for(
                response,
                attempt=attempt,
                cap=cap,
                rng=random_source,
                base=base,
                now=now,
            )
        )
    raise RuntimeError("retry loop exited without a response")
