"""Exceptions raised by the SDK and proxy."""

from __future__ import annotations


class WatchError(Exception):
    """Base error. `call_id` is set once a ledger row exists."""

    def __init__(self, message: str, *, call_id: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.call_id = call_id
        self.status_code = status_code


class WatchProviderError(WatchError):
    """The provider failed, or retries were exhausted. The attempt is already logged."""
