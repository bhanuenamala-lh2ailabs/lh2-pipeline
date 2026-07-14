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

import calendar
from typing import Optional

from .logging_setup import get_logger
from .quota_ledger import QuotaExceeded, QuotaLedger
from .ratelimit import RateLimiter

log = get_logger("lh2.governor")

CREDIT_METRIC = "credits"   # contact reveals (email + phone), monthly-budgeted


class Governor:
    def __init__(self, provider: str, rate: RateLimiter, ledger: QuotaLedger,
                 monthly_credit_budget: Optional[int] = None):
        self.provider = provider
        self.rate = rate
        self.ledger = ledger
        self.monthly_credit_budget = monthly_credit_budget

    def pace(self, n: float = 1.0) -> float:
        return self.rate.acquire(n)

    def remaining(self, metric: str) -> Optional[int]:
        return self.ledger.remaining(metric)

    def would_exceed(self, metric: str, n: int = 1) -> bool:
        return self.ledger.would_exceed(metric, n)

    def check_and_charge(self, metric: str, n: int = 1) -> int:
        """Raise QuotaExceeded if we're at the cap; otherwise record the spend."""
        return self.ledger.charge(metric, n)   # charge() raises before recording

    # -- monthly credit budget with fair daily pacing --------------------- #
    # Credits are stored per-DAY (window "YYYY-MM-DD"); the month total is the sum
    # of the month's daily rows. Each day's allowance = remaining_budget /
    # days_left_in_month, so a skipped/heavy day self-levels and the month never
    # crosses the budget. Persistent -> holds across runs and restarts.
    def _now(self):
        return self.ledger._now()

    def credit_month_used(self) -> int:
        return self.ledger.store.quota_sum(self.provider, CREDIT_METRIC,
                                           self._now().strftime("%Y-%m"))

    def credit_today_used(self) -> int:
        used, _ = self.ledger.store.quota_get(self.provider, CREDIT_METRIC,
                                              self._now().strftime("%Y-%m-%d"))
        return used

    def credit_daily_budget(self) -> Optional[int]:
        """Today's fair-share allowance: (budget spent-before-today) spread over the
        days left. Computed from the month state *before today* so it stays fixed
        as today's reveals are spent (otherwise it would shrink under its own use)."""
        if not self.monthly_credit_budget:
            return None
        now = self._now()
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        days_left = max(1, days_in_month - now.day + 1)
        used_before_today = self.credit_month_used() - self.credit_today_used()
        remaining_before_today = max(0, self.monthly_credit_budget - used_before_today)
        return -(-remaining_before_today // days_left)          # ceil division

    def credits_available_today(self) -> bool:
        """True if another reveal is allowed now: monthly cap not hit AND today's
        fair-share budget not yet spent. Uncapped provider -> always True."""
        if not self.monthly_credit_budget:
            return True
        if self.credit_month_used() >= self.monthly_credit_budget:
            return False
        return self.credit_today_used() < (self.credit_daily_budget() or 0)

    def charge_credit(self, n: int = 1) -> None:
        """Record ``n`` spent reveal credits, day-windowed. Gating happens in
        :meth:`credits_available_today` (checked before each reveal), so this just
        accounts the spend."""
        self.ledger.store.quota_add(self.provider, CREDIT_METRIC,
                                    self._now().strftime("%Y-%m-%d"), n)

    def require_credit(self) -> None:
        """Raise QuotaExceeded if no reveal credit is available today (daily budget
        spent or monthly cap hit). Called before a reveal."""
        if not self.credits_available_today():
            raise QuotaExceeded(self.provider, CREDIT_METRIC,
                                self.credit_month_used(), self.monthly_credit_budget or 0)


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
    gov = Governor(provider, rate, ledger, monthly_credit_budget=pc.monthly_credit_budget)
    log.info("governor_built", provider=provider,
             rate_limited=not rate.unlimited,
             search_remaining=ledger.remaining("search"),
             monthly_credit_budget=pc.monthly_credit_budget,
             credits_today_budget=gov.credit_daily_budget())
    return gov


__all__ = ["Governor", "build_governor", "QuotaExceeded"]
