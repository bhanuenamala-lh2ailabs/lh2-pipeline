"""Per-provider governor = rate limiter (short-term pacing) + quota ledger
(durable long-horizon caps), built from ``config.providers.<name>``.

Call pattern from a provider adapter:
  * ``governor.pace()``                     — before every HTTP request (blocks to respect rate)
  * ``governor.check_and_charge('search')`` — before spending a scarce quota unit;
                                              raises QuotaExceeded when the cap is hit
  * ``governor.remaining('search')``        — for the pacing scheduler / dry-run preview

When a provider's quota is exhausted the adapter propagates QuotaExceeded; the
enrich loop catches it and stops cleanly (the work done so far is cached, so the
next run resumes rather than restarts). With multiple providers this is where the
waterfall would spill over to the next source instead of stopping.
"""

from __future__ import annotations

from typing import Optional

from .logging_setup import get_logger
from .quota_ledger import QuotaExceeded, QuotaLedger
from .ratelimit import RateLimiter

log = get_logger("lh2.governor")


class Governor:
    def __init__(self, provider: str, rate: RateLimiter, ledger: QuotaLedger):
        self.provider = provider
        self.rate = rate
        self.ledger = ledger

    def pace(self, n: float = 1.0) -> float:
        return self.rate.acquire(n)

    def remaining(self, metric: str) -> Optional[int]:
        return self.ledger.remaining(metric)

    def would_exceed(self, metric: str, n: int = 1) -> bool:
        return self.ledger.would_exceed(metric, n)

    def check_and_charge(self, metric: str, n: int = 1) -> int:
        """Raise QuotaExceeded if we're at the cap; otherwise record the spend."""
        return self.ledger.charge(metric, n)   # charge() raises before recording


def build_governor(cfg, store, provider: str) -> Optional[Governor]:  # noqa: ANN001
    """Construct a Governor for ``provider`` from config, or None if no providers
    config is present (limiter/ledger absent → callers proceed unthrottled)."""
    providers = getattr(cfg, "providers", None)
    if providers is None:
        return None
    pc = providers.provider(provider)
    if pc is None:
        return None
    margin = providers.defaults.safety_margin
    limits = pc.limits.model_dump(exclude_none=True)
    rate = RateLimiter.from_limits(limits, safety_margin=margin)
    ledger = QuotaLedger(store, provider, limits, reset=pc.reset, safety_margin=margin)
    log.info("governor_built", provider=provider,
             rate_limited=not rate.unlimited,
             search_remaining=ledger.remaining("search"))
    return Governor(provider, rate, ledger)


__all__ = ["Governor", "build_governor", "QuotaExceeded"]
