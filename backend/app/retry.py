"""Retry for transient Gemini failures.

A rate limit or a momentarily overloaded model is the likeliest way a live
demo breaks, and it used to break loudly: the first 429 propagated out of the
agent tree, every model stage was marked failed, and the console showed
"Live pipeline failed". Those are precisely the errors that succeed on a second
attempt seconds later, so they are worth absorbing rather than surfacing.

Only transient statuses are retried. A bad key (403) or a malformed request
(400) will fail identically on every attempt, and retrying them would turn an
instant, legible error into a slow one.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

# 429 rate limit / quota, 500 internal, 503 overloaded-or-unavailable.
RETRYABLE_CODES = {429, 500, 503}
RETRYABLE_STATUSES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"}

MAX_ATTEMPTS = 4
# A cap on cumulative sleeping. Vertex serves the larger models from a shared
# capacity pool, and pressure on it lasts tens of seconds — 30s of patience
# gave up while the pool was still busy. A demo would rather wait a little
# longer than show an error, but not so long that the page looks hung, and the
# caller falls back to a smaller model once this is exhausted.
MAX_TOTAL_WAIT_SECONDS = 60.0


def _causes(exc: BaseException):
    """Walk the exception chain — ADK wraps the underlying genai error."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_retryable(exc: BaseException) -> bool:
    for err in _causes(exc):
        code = getattr(err, "code", None)
        if isinstance(code, int) and code in RETRYABLE_CODES:
            return True
        status = getattr(err, "status", None)
        if isinstance(status, str) and status.upper() in RETRYABLE_STATUSES:
            return True
    return False


def _server_retry_delay(exc: BaseException) -> float | None:
    """The delay Gemini asks for, when its 429 payload carries a RetryInfo.

    Honouring the server's own number beats guessing: it knows when the quota
    window actually rolls over.
    """
    match = re.search(
        r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE
    )
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


async def with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    label: str = "gemini",
    on_retry: Callable[[int, float, str], None] | None = None,
) -> T:
    """Await `call()`, retrying transient Gemini failures with backoff.

    `call` must be a factory rather than a coroutine, because a coroutine
    cannot be awaited twice — each attempt needs a fresh one.
    """
    waited = 0.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 — non-retryable is re-raised below
            if attempt == MAX_ATTEMPTS or not is_retryable(exc):
                raise

            delay = _server_retry_delay(exc)
            if delay is None:
                delay = min(2.0 * 2 ** (attempt - 1), 8.0)
            # Jitter so two stacked retries don't resynchronise onto the same
            # instant and collide again.
            delay += random.uniform(0, 0.5)

            if waited + delay > MAX_TOTAL_WAIT_SECONDS:
                raise
            waited += delay

            reason = f"{type(exc).__name__}: {exc}"[:200]
            if on_retry:
                on_retry(attempt, delay, reason)
            else:
                print(
                    f"[retry] {label} attempt {attempt}/{MAX_ATTEMPTS} failed, "
                    f"retrying in {delay:.1f}s - {reason}",
                    flush=True,
                )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


def with_retry_sync(call: Callable[[], T], *, label: str = "gemini") -> T:
    """Blocking twin of `with_retry`, for the embedding path.

    Embeddings are computed synchronously inside `asyncio.to_thread`, so they
    cannot await the async version.
    """
    waited = 0.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 — non-retryable is re-raised below
            if attempt == MAX_ATTEMPTS or not is_retryable(exc):
                raise

            delay = _server_retry_delay(exc)
            if delay is None:
                delay = min(2.0 * 2 ** (attempt - 1), 8.0)
            delay += random.uniform(0, 0.5)

            if waited + delay > MAX_TOTAL_WAIT_SECONDS:
                raise
            waited += delay

            print(
                f"[retry] {label} attempt {attempt}/{MAX_ATTEMPTS} failed, "
                f"retrying in {delay:.1f}s - {type(exc).__name__}: {str(exc)[:160]}",
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover
