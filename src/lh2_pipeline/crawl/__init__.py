"""Phase 1 crawlers + orchestration.

`run_crawl` drives enabled sources × cities, paginating until a page yields no
rows, fetching via Playwright (cache-first), parsing with each source's isolated
selectors, and writing `raw_listings`. A hard anti-bot block on one source is
logged and skipped — it never crashes the whole run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Type

from ..logging_setup import get_logger
from .base import BaseCrawler, BlockedError, CrawlSettings, FetchError, PlaywrightFetcher
from .clutch import ClutchCrawler
from .designrush import DesignRushCrawler
from .goodfirms import GoodFirmsCrawler
from .manifest import ManifestCrawler
from .nasscom import NasscomCrawler
from .techbehemoths import TechBehemothsCrawler

log = get_logger("lh2.crawl")

REGISTRY: dict[str, Type[BaseCrawler]] = {
    "goodfirms": GoodFirmsCrawler,
    "clutch": ClutchCrawler,
    "techbehemoths": TechBehemothsCrawler,
    "manifest": ManifestCrawler,
    "designrush": DesignRushCrawler,
    "nasscom": NasscomCrawler,
}


def _settings(cfg) -> CrawlSettings:  # noqa: ANN001
    return CrawlSettings(
        raw_html_dir=cfg.raw_html_dir,
        user_agents=cfg.crawl.user_agents,
        delay_min_s=cfg.crawl.delay_min_seconds,
        delay_max_s=cfg.crawl.delay_max_seconds,
        timeout_s=cfg.crawl.request_timeout_seconds,
        retry_attempts=cfg.crawl.retry_attempts,
        honor_robots=cfg.crawl.honor_robots,
    )


def _make_crawler(name: str, fetcher, cfg) -> BaseCrawler:  # noqa: ANN001
    cls = REGISTRY[name]
    return cls(fetcher, _settings(cfg), max_pages=cfg.crawl.max_pages_per_city)


def run_crawl(cfg, store, source=None, city=None, refresh=False) -> dict:  # noqa: ANN001
    """Crawl one/all sources across one/all cities into `raw_listings`.

    Returns a per-source stats dict. Requires Playwright (lazy)."""
    sources = [source] if source else cfg.crawl.enabled_sources()
    sources = [s for s in sources if s in REGISTRY]
    if not sources:
        log.info("crawl_no_sources")
        return {}
    cities = [city] if city else cfg.crawl.cities

    fetcher = PlaywrightFetcher()
    stats: dict[str, dict] = {}
    try:
        for src in sources:
            crawler = _make_crawler(src, fetcher, cfg)
            s = stats.setdefault(src, {"pages": 0, "rows": 0, "blocked": False, "skipped": 0})
            for c in cities:
                try:
                    _crawl_city(crawler, store, c, refresh, s)
                except BlockedError as e:
                    log.info("source_blocked", source=src, city=c, err=str(e))
                    s["blocked"] = True
                    break  # skip the rest of this source's cities
                except FetchError as e:
                    log.info("city_fetch_failed", source=src, city=c, err=str(e))
                    s["skipped"] += 1
            log.info("source_done", source=src, **s)
    finally:
        try:
            fetcher.close()
        except Exception:
            pass

    total = sum(v["rows"] for v in stats.values())
    log.info("crawl_complete", total_rows=total, sources=list(stats))
    return stats


def _crawl_city(crawler: BaseCrawler, store, city: str, refresh: bool, s: dict) -> None:  # noqa: ANN001
    for url in crawler.city_urls(city):
        html = crawler.get(url, refresh=refresh)   # may raise Blocked/FetchError
        rows = crawler.parse(html, url, city)
        s["pages"] += 1
        if not rows:
            # Empty page → end of pagination for this city.
            break
        for r in rows:
            store.insert_raw_listing(r)
        s["rows"] += len(rows)
        log.debug("city_page", source=crawler.source, city=city, url=url, rows=len(rows))


def smoke(cfg, source: str, city: str) -> int:  # noqa: ANN001
    """Fetch ONE known city page (page 1) for `source` and return the parsed row
    count. The Phase-1 smoke-test gate: asserts ≥1 row with a non-empty name."""
    fetcher = PlaywrightFetcher()
    try:
        crawler = _make_crawler(source, fetcher, cfg)
        url = crawler.city_urls(city)[0]
        html = crawler.get(url, refresh=True)
        rows = crawler.parse(html, url, city)
        named = [r for r in rows if r.company_name.strip()]
        log.info("smoke", source=source, city=city, url=url, rows=len(rows), named=len(named))
        return len(named)
    finally:
        try:
            fetcher.close()
        except Exception:
            pass
