"""The Manifest crawler — India software-dev directory; secondary cross-fill.

================================ SELECTORS ===================================
Best-effort; confirm with `lh2-smoke manifest`. Fix only these on drift.
NOTE: not yet confirmed against live DOM.
=============================================================================
"""

from __future__ import annotations

from typing import Optional

from ..models import RawListing
from .base import BaseCrawler
from .parsing import attr, clean_website, first, soup, text

# --- isolated selectors ---------------------------------------------------- #
SEL_CARD = "li.provider-row, div.provider-card, ul.directory-list > li"
SEL_NAME = "h3 a, .company-name a, a.company_title"
SEL_WEBSITE = "a.website-link__item, a.visit-website, a[data-link-type='website']"
SEL_CITY = ".locality, .location"
SEL_FOUNDED = ".founded, li.founded"
SEL_SIZE = ".employees, .company-size"
SEL_SEGMENT = ".tagline, .service-focus"

BASE = "https://themanifest.com"
PATH_TEMPLATE = "/in/software-development/{city_slug}/companies"


def city_slug(city: str) -> str:
    return city.strip().lower().replace(" ", "-")


class ManifestCrawler(BaseCrawler):
    source = "manifest"

    def __init__(self, fetcher, settings, max_pages: int = 50):
        super().__init__(fetcher, settings)
        self.max_pages = max_pages

    def city_urls(self, city: str) -> list[str]:
        path = PATH_TEMPLATE.format(city_slug=city_slug(city))
        return [f"{BASE}{path}?page={p}" for p in range(0, self.max_pages)]

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
