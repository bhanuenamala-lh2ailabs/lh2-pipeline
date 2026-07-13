"""BaseCrawler: fetch, throttle, cache, retry, UA rotation, robots.

Design: fetching is separated from parsing.
  * A ``Fetcher`` returns HTML for a URL (PlaywrightFetcher for real runs;
    a fake one in tests). BaseCrawler wraps it with throttle + gzip cache +
    retry/backoff + user-agent rotation + robots checks.
  * Each source module provides a pure ``parse(html, url, city) -> [RawListing]``
    with its CSS selectors isolated at the top — unit-testable on fixtures.

Caching: every fetched page is gzipped to ``data/raw_html/<sha1(url)>.html.gz``.
Re-runs read cache unless ``refresh=True``. A Cloudflare hard-block is logged
and surfaced as ``BlockedError`` so the orchestrator can skip the source, not
crash the run.
"""

from __future__ import annotations

import gzip
import hashlib
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from ..logging_setup import get_logger

log = get_logger("lh2.crawl")


class BlockedError(Exception):
    """Raised when a host hard-blocks (e.g. Cloudflare challenge)."""


class FetchError(Exception):
    """Transient fetch failure (retryable)."""


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #
class Fetcher(Protocol):
    def fetch(self, url: str, user_agent: str, timeout_s: int) -> str: ...


# Markers that usually indicate a Cloudflare/anti-bot interstitial rather than
# the real page. Isolated here so they're easy to extend.
_BLOCK_MARKERS = (
    "cf-browser-verification",
    "Checking your browser before accessing",
    "Just a moment...",
    "Attention Required! | Cloudflare",
    "Please enable JavaScript and cookies",
)


def looks_blocked(html: str) -> bool:
    sample = html[:4000]
    return any(m in sample for m in _BLOCK_MARKERS)


class PlaywrightFetcher:
    """Headless Chromium fetch. Playwright imported lazily so the package (and
    tests) work without it installed."""

    def __init__(self, headless: bool = True, wait_until: str = "networkidle"):
        self.headless = headless
        self.wait_until = wait_until
        self._pw = None
        self._browser = None

    def _ensure(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "playwright is required for live crawling. "
                "Install with: pip install -e \".[crawl]\" && python -m playwright install chromium"
            ) from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)

    def fetch(self, url: str, user_agent: str, timeout_s: int) -> str:
        self._ensure()
        ctx = self._browser.new_context(user_agent=user_agent)
        page = ctx.new_page()
        try:
            page.goto(url, timeout=timeout_s * 1000, wait_until=self.wait_until)
            html = page.content()
            return html
        except Exception as e:  # pragma: no cover - network dependent
            raise FetchError(f"playwright goto failed for {url}: {e}") from e
        finally:
            ctx.close()

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


# --------------------------------------------------------------------------- #
# BaseCrawler
# --------------------------------------------------------------------------- #
@dataclass
class CrawlSettings:
    raw_html_dir: Path
    user_agents: list[str]
    delay_min_s: float = 2.0
    delay_max_s: float = 5.0
    timeout_s: int = 45
    retry_attempts: int = 3
    honor_robots: bool = True
    # Injectable sleep/random for deterministic tests.
    sleep: Callable[[float], None] = time.sleep
    jitter: Callable[[float, float], float] = random.uniform
    ua_pick: Optional[Callable[[list[str]], str]] = None


class BaseCrawler:
    """Shared crawl plumbing. Subclasses set ``source`` and implement
    ``city_urls(city)`` and ``parse(html, url, city)``."""

    source: str = "base"

    def __init__(self, fetcher: Fetcher, settings: CrawlSettings):
        self.fetcher = fetcher
        self.s = settings
        self.s.raw_html_dir.mkdir(parents=True, exist_ok=True)
        self._robots: dict[str, RobotFileParser] = {}

    # -- cache ------------------------------------------------------------- #
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.s.raw_html_dir / f"{self.source}_{h}.html.gz"

    def cache_read(self, url: str) -> Optional[str]:
        p = self._cache_path(url)
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return fh.read()
        return None

    def cache_write(self, url: str, html: str) -> None:
        p = self._cache_path(url)
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            fh.write(html)

    # -- politeness -------------------------------------------------------- #
    def _pick_ua(self) -> str:
        uas = self.s.user_agents or ["LH2Bot/0.1 (+contact: data@lh2.ai)"]
        if self.s.ua_pick:
            return self.s.ua_pick(uas)
        return random.choice(uas)

    def _throttle(self) -> None:
        self.s.sleep(self.s.jitter(self.s.delay_min_s, self.s.delay_max_s))

    def _robots_ok(self, url: str, ua: str) -> bool:
        if not self.s.honor_robots:
            return True
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:
                # If robots can't be fetched, default to allowed but log it.
                log.info("robots_unreadable", host=base)
                rp = None  # type: ignore
            self._robots[base] = rp  # type: ignore
        if rp is None:
            return True
        return rp.can_fetch(ua, url)

    # -- fetch ------------------------------------------------------------- #
    def get(self, url: str, refresh: bool = False) -> str:
        """Return HTML for ``url`` (cache-first). Raises BlockedError on a
        hard anti-bot block; FetchError after exhausting retries."""
        if not refresh:
            cached = self.cache_read(url)
            if cached is not None:
                log.debug("cache_hit", source=self.source, url=url)
                return cached

        ua = self._pick_ua()
        if not self._robots_ok(url, ua):
            raise BlockedError(f"robots.txt disallows {url}")

        last: Optional[Exception] = None
        for attempt in range(1, self.s.retry_attempts + 1):
            try:
                self._throttle()
                html = self.fetcher.fetch(url, ua, self.s.timeout_s)
                if looks_blocked(html):
                    raise BlockedError(f"anti-bot interstitial at {url}")
                self.cache_write(url, html)
                return html
            except BlockedError:
                raise
            except Exception as e:  # transient
                last = e
                backoff = min(30.0, (2 ** attempt) + self.s.jitter(0, 1))
                log.info("fetch_retry", url=url, attempt=attempt, err=str(e))
                self.s.sleep(backoff)
        raise FetchError(f"failed after {self.s.retry_attempts} attempts: {last}")

    # -- subclass contract ------------------------------------------------- #
    def city_urls(self, city: str) -> list[str]:
        """Yield the listing page URLs for a city (page 1.. up to cap)."""
        raise NotImplementedError

    def parse(self, html: str, url: str, city: str):  # -> list[RawListing]
        raise NotImplementedError
