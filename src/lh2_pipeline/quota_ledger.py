"""Persistent per-provider quota accounting.

The rate limiter handles *short-term* pacing; this handles *long-horizon* caps —
daily search quotas, monthly credit pools — the limits that a single process
can't see by pacing alone. Consumption is written to the ``quota`` table (not
memory) so a killed-and-restarted run never double-spends or forgets it was near
a cap. That durability is what makes the engine safe to run unattended.

Each metric maps to a reset window:
  * ``daily_utc``   -> key "YYYY-MM-DD" (resets at UTC midnight)
  * ``monthly``     -> key "YYYY-MM"
  * ``none``/other  -> key "all" (never resets — e.g. prepaid credits)

Limits are scaled by ``safety_margin`` so we stop short of the true ceiling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from .logging_setup import get_logger
from .models import utcnow

log = get_logger("lh2.quota")


class QuotaExceeded(Exception):
    """Raised when a charge would exceed a provider's (safety-margined) quota."""

    def __init__(self, provider: str, metric: str, used: int, limit: int):
        self.provider = provider
        self.metric = metric
        self.used = used
        self.limit = limit
        super().__init__(f"{provider}:{metric} quota reached ({used}/{limit})")


def window_key(reset: str, now: datetime) -> str:
    r = (reset or "").lower()
    if r == "daily_utc" or r == "daily":
        return now.strftime("%Y-%m-%d")
    if r == "monthly":
        return now.strftime("%Y-%m")
    return "all"


# Which limit key backs each logical metric.
_METRIC_LIMIT_KEYS = {
    "search": ("search_per_day",),
    "requests": ("requests_per_day",),
    "credits": ("monthly_credits", "free_calls_per_month"),
}


class QuotaLedger:
    """Durable quota accounting for one provider, across its metrics."""

    def __init__(
        self,
        store,                              # noqa: ANN001
        provider: str,
        limits: dict,
        reset: str = "daily_utc",
        safety_margin: float = 0.8,
        now_fn: Callable[[], datetime] = utcnow,
    ):
        self.store = store
        self.provider = provider
        self.limits = limits or {}
        self.reset = reset
        self.safety_margin = safety_margin
        self._now = now_fn

    # -- limit lookup ------------------------------------------------------ #
    def effective_limit(self, metric: str) -> Optional[int]:
        """Safety-margined integer cap for a metric, or None if uncapped."""
        raw = None
        for key in _METRIC_LIMIT_KEYS.get(metric, (f"{metric}_per_day",)):
            if self.limits.get(key) is not None:
                raw = self.limits[key]
                break
        if raw is None:
            return None
        return max(1, int(raw * self.safety_margin))

    def _key(self, metric: str) -> str:
        # credits use the monthly window; per-day metrics use the provider reset.
        reset = "monthly" if metric == "credits" and self.reset != "monthly" else self.reset
        if metric == "credits" and self.limits.get("free_calls_per_month") is not None:
            reset = "monthly"
        return window_key(reset, self._now())

    # -- accounting -------------------------------------------------------- #
    def used(self, metric: str) -> int:
        u, _ = self.store.quota_get(self.provider, metric, self._key(metric))
        return u

    def remaining(self, metric: str) -> Optional[int]:
        limit = self.effective_limit(metric)
        if limit is None:
            return None
        return max(0, limit - self.used(metric))

    def would_exceed(self, metric: str, n: int = 1) -> bool:
        rem = self.remaining(metric)
        return rem is not None and n > rem

    def charge(self, metric: str, n: int = 1) -> int:
        """Record ``n`` units against a metric. Raises QuotaExceeded (without
        recording) if that would breach the safety-margined cap."""
        limit = self.effective_limit(metric)
        if limit is not None and self.used(metric) + n > limit:
            raise QuotaExceeded(self.provider, metric, self.used(metric), limit)
        return self.store.quota_add(self.provider, metric, self._key(metric), n, limit)
