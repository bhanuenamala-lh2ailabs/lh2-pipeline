"""NASSCOM member-directory crawler — India-only by definition; good breadth
and a strong India-HQ signal.

================================ SELECTORS ===================================
Best-effort; confirm with `lh2-smoke nasscom`. Fix only these on drift.
NASSCOM's member directory is search/filter driven and may require interacting
with the page (the Playwright fetcher loads JS). City is captured from the
profile/location field rather than the URL where the directory is not city-sliced.
NOTE: not yet confirmed against live DOM.
=============================================================================
"""

from __future__ import annotations

from typing import Optional

from ..models import RawListing
from .base import BaseCrawler
from .parsing import attr, clean_website, first, soup, text

# --- isolated selectors ---------------------------------------------------- #
SEL_CARD = "div.member-card, li.member, .members-list .member"
SEL_NAME = ".member-name, h3 a, .company-name"
SEL_WEBSITE = "a.member-website, a.visit-website, a[target='_blank'][rel~='nofollow']"
SEL_CITY = ".member-location, .location, .city"
SEL_FOUNDED = ".member-founded, .founded"
SEL_SIZE = ".member-employees, .employees, .company-size"
SEL_SEGMENT = ".member-category, .segment, .services"

BASE = "https://www.nasscom.in"
# Member directory is filter-driven; ?location= drives the city facet.
DIRECTORY_PATH = "/membership/member-directory"


class NasscomCrawler(BaseCrawler):
    source = "nasscom"

    def __init__(self, fetcher, settings, max_pages: int = 50):
        super().__init__(fetcher, settings)
        self.max_pages = max_pages

    def city_urls(self, city: str) -> list[str]:
        c = city.strip()
        return [
            f"{BASE}{DIRECTORY_PATH}?location={c}&page={p}"
            for p in range(1, self.max_pages + 1)
        ]

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
