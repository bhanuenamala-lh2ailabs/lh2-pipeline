"""DesignRush crawler — India software-dev directory; secondary cross-fill.

================================ SELECTORS ===================================
Best-effort; confirm with `lh2-smoke designrush`. Fix only these on drift.
NOTE: not yet confirmed against live DOM.
=============================================================================
"""

from __future__ import annotations

from typing import Optional

from ..models import RawListing
from .base import BaseCrawler
from .parsing import attr, clean_website, first, soup, text

# --- isolated selectors ---------------------------------------------------- #
SEL_CARD = "div.agency-listing, li.agency, .agencies-list .agency"
SEL_NAME = ".agency-name a, h3 a, .company-name"
SEL_WEBSITE = "a.visit-website, a.agency-website, a[target='_blank'][rel~='nofollow']"
SEL_CITY = ".agency-location, .location"
SEL_FOUNDED = ".agency-founded, .founded"
SEL_SIZE = ".agency-employees, .employees, .company-size"
SEL_SEGMENT = ".agency-services, .tagline, .services"

BASE = "https://www.designrush.com"
PATH_TEMPLATE = "/agency/software-development/india/{city_slug}"


def city_slug(city: str) -> str:
    return city.strip().lower().replace(" ", "-")


class DesignRushCrawler(BaseCrawler):
    source = "designrush"

    def __init__(self, fetcher, settings, max_pages: int = 50):
        super().__init__(fetcher, settings)
        self.max_pages = max_pages

    def city_urls(self, city: str) -> list[str]:
        path = PATH_TEMPLATE.format(city_slug=city_slug(city))
        return [f"{BASE}{path}?page={p}" for p in range(1, self.max_pages + 1)]

    def parse(self, html: str, url: str, city: str) -> list[RawListing]:
        s = soup(html)
        rows: list[RawListing] = []
        for card in s.select(SEL_CARD):
            name = text(first(card, SEL_NAME))
            if not name:
                continue
            web = first(card, SEL_WEBSITE)
            rows.append(
                RawListing(
                    source=self.source,
                    source_url=url,
                    company_name=name,
                    website_raw=clean_website(attr(web, "href")) if web else None,
                    city=text(first(card, SEL_CITY)) or city,
                    founded_year_raw=_opt(text(first(card, SEL_FOUNDED))),
                    size_raw=_opt(text(first(card, SEL_SIZE))),
                    segment_raw=_opt(text(first(card, SEL_SEGMENT))),
                )
            )
        return rows


def _opt(v: str) -> Optional[str]:
    return v or None
