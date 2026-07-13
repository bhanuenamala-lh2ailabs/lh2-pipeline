"""GoodFirms crawler — India software-development directory, per-city pages.

Listing rows expose founded year, team size, location inline → highest yield.

================================ SELECTORS ===================================
GoodFirms renders server-side. Selectors below are best-effort and MUST be
confirmed by the live smoke test (`lh2-smoke goodfirms`). If GoodFirms changes
its markup, fix ONLY the constants in this block.
NOTE: not yet confirmed against live DOM (crawl env blocks non-browser fetches).
=============================================================================
"""

from __future__ import annotations

from typing import Optional

from ..models import RawListing
from .base import BaseCrawler
from .parsing import attr, clean_website, first, soup, text

# --- isolated selectors (confirmed against live DOM 2026-06) ---------------- #
SEL_CARD = "li.firm-wrapper"                       # one company card
SEL_NAME = "h3.firm-name a"
SEL_WEBSITE = ".firm-urls a.visit-website, a.visit-website"
SEL_CITY = ".firm-location span"
SEL_FOUNDED = ".firm-founded span"
SEL_SIZE = ".firm-employees span"
SEL_SEGMENT = ".firm-short-description"

BASE = "https://www.goodfirms.co"
# Confirmed live (2026-06): per-city software-development directory, paginated ?page=N.
# e.g. https://www.goodfirms.co/directory/city/top-software-development-companies/pune
CITY_PATH = "/directory/city/top-software-development-companies/{slug}"


# GoodFirms uses some legacy city slugs that differ from the modern city name.
CITY_SLUG_OVERRIDES = {
    "bengaluru": "bangalore",
    "gurugram": "gurgaon",
    "trivandrum": "thiruvananthapuram",
}


def city_slug(city: str) -> str:
    slug = city.strip().lower().replace(" ", "-")
    return CITY_SLUG_OVERRIDES.get(slug, slug)


class GoodFirmsCrawler(BaseCrawler):
    source = "goodfirms"

    def __init__(self, fetcher, settings, max_pages: int = 50):
        super().__init__(fetcher, settings)
        self.max_pages = max_pages

    def city_urls(self, city: str) -> list[str]:
        slug = city_slug(city)
        path = CITY_PATH.format(slug=slug)
        return [f"{BASE}{path}?page={p}" for p in range(1, self.max_pages + 1)]

    def parse(self, html: str, url: str, city: str) -> list[RawListing]:
        s = soup(html)
        rows: list[RawListing] = []
        for card in s.select(SEL_CARD):
            name = text(first(card, SEL_NAME))
            if not name:
                continue
            web_node = first(card, SEL_WEBSITE)
            website = clean_website(attr(web_node, "href")) if web_node else None
            rows.append(
                RawListing(
                    source=self.source,
                    source_url=url,
                    company_name=name,
                    website_raw=website,
                    city=text(first(card, SEL_CITY)) or city,
                    founded_year_raw=_opt(text(first(card, SEL_FOUNDED))),
                    size_raw=_opt(text(first(card, SEL_SIZE))),
                    segment_raw=_opt(text(first(card, SEL_SEGMENT))),
                )
            )
        return rows


def _opt(v: str) -> Optional[str]:
    return v or None
