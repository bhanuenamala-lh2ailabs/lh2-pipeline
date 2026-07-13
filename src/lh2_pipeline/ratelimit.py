"""Multi-window token-bucket rate limiter.

Enforces short-term request pacing (per-second / per-minute / per-hour) so we
*proactively* stay under a provider's documented rate — as opposed to reacting to
a 429 after the fact. Every configured window is honoured simultaneously; the
limiter blocks (sleeps) until a request may proceed under all of them.

Rates are scaled by ``safety_margin`` (default 0.8) so we deliberately run below
the stated ceiling. Clock + sleep are injectable so tests use a fake clock and
never actually wait.

The pipeline is synchronous (one request at a time), so a blocking limiter is the
right fit; the token-bucket math generalizes to async later without changing the
call sites.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class _Bucket:
    """A single leaky/token bucket: ``rate`` tokens/sec, capacity ``capacity``."""

    def __init__(self, rate: float, capacity: float, clock: Callable[[], float]):
        self.rate = rate
        self.capacity = max(1.0, capacity)
        self.tokens = self.capacity
        self._clock = clock
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self._last = now

    def time_until(self, n: float) -> float:
        """Seconds until ``n`` tokens are available (0 if available now)."""
        self._refill()
        if self.tokens >= n:
            return 0.0
        return (n - self.tokens) / self.rate if self.rate > 0 else float("inf")

    def consume(self, n: float) -> None:
        self._refill()
        self.tokens -= n


class RateLimiter:
    """Blocks on :meth:`acquire` until a request fits every configured window."""

    def __init__(
        self,
        per_second: Optional[float] = None,
        per_minute: Optional[float] = None,
        per_hour: Optional[float] = None,
        safety_margin: float = 0.8,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._buckets: list[_Bucket] = []
        for limit, period in ((per_second, 1.0), (per_minute, 60.0), (per_hour, 3600.0)):
            if limit and limit > 0:
                eff = limit * safety_margin
                self._buckets.append(_Bucket(rate=eff / period, capacity=eff, clock=clock))

    @property
    def unlimited(self) -> bool:
        return not self._buckets

    def acquire(self, n: float = 1.0) -> float:
        """Block until ``n`` tokens are available under every window. Returns the
        total seconds waited (0 if no wait)."""
        waited = 0.0
        while True:
            wait = max((b.time_until(n) for b in self._buckets), default=0.0)
            if wait <= 0:
                for b in self._buckets:
                    b.consume(n)
                return waited
            self._sleep(wait)
            waited += wait

    @classmethod
    def from_limits(cls, limits: dict, safety_margin: float = 0.8, **kw) -> "RateLimiter":
        """Build from a provider ``limits`` dict, reading the rate-window keys and
        ignoring the quota keys (those are the QuotaLedger's job)."""
        pm = limits.get("requests_per_minute") or limits.get("person_items_per_minute")
        return cls(
            per_second=limits.get("requests_per_second"),
            per_minute=pm,
            per_hour=limits.get("requests_per_hour"),
            safety_margin=safety_margin,
            **kw,
        )
