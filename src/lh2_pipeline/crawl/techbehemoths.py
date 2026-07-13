"""TechBehemoths crawler — per-city company lists.

================================ SELECTORS ===================================
Confirmed against live DOM 2026-07-13 via `lh2 smoke techbehemoths`.
City listing URL is `/companies/<city-slug>` (NOT `/companies/all/...`, which is
a dead landing page). Cards are `.co-box`.

LIMITATION: the listing card exposes name + website + location + description, but
NOT founded-year or employee-size — those live on each firm's profile page. So
firms captured here fail the founded/size gate until a profile-page fetch is
added (see `parse_profile` stub / follow-up). They are still captured in
raw_listings (and cross-fill founded/size for firms other sources already have).
=============================================================================
"""

from __future__ import annotations

from typing import Optional

from ..models import RawListing
from .base import BaseCrawler
from .parsing import attr, clean_website, first, soup, text

# --- isolated selectors (confirmed live 2026-07-13) ------------------------ #
SEL_CARD = ".co-box"                        # one company card
SEL_NAME = "p.co-box__name"                 # contains a nested "Verified Company" span
SEL_VERIFIED = ".verified--ico"             # removed from the name before reading it
SEL_WEBSITE = "a.btn-website"               # external site (with UTM query to strip)
SEL_LOC = "span.co-box__loc-itm"            # first = "Pune , India"
SEL_DESCR = "p.co-box__descr"               # short blurb -> segment
# Not present on the listing card (profile-page only):
# SEL_FOUNDED, SEL_SIZE — see module docstring.

BASE = "https://techbehemoths.com"
PATH_TEMPLATE = "/companies/{city_slug}"


def city_slug(city: str) -> str:
    return city.strip().lower().replace(" ", "-")


def _clean_name(card) -> str:  # noqa: ANN001
    """Company name from the card, with the 'Verified Company' badge removed."""
    node = first(card, SEL_NAME)
    if node is None:
        return ""
    badge = node.select_one(SEL_VERIFIED)
    if badge is not None:
        badge.extract()
    return text(node)


class TechBehemothsCrawler(BaseCrawler):
    source = "techbehemoths"

    def __init__(self, fetcher, settings, max_pages: int = 50):
        super().__init__(fetcher, settings)
        self.max_pages = max_pages

    def city_urls(self, city: str) -> list[str]:
        # Page 1 only for now: the list uses JS "load more" rather than ?page=N,
        # so deeper pagination is a follow-up. ~20-25 firms/city on page 1.
        return [f"{BASE}{PATH_TEMPLATE.format(city_slug=city_slug(city))}"]

    def parse(self, html: str, url: str, city: str) -> list[RawListing]:
        s = soup(html)
        rows: list[RawListing] = []
        for card in s.select(SEL_CARD):
            name = _clean_name(card)
            if not name:
                continue
            web = first(card, SEL_WEBSITE)
            loc = first(card, SEL_LOC)
            rows.append(
                RawListing(
                    source=self.source,
                    source_url=url,
                    company_name=name,
                    website_raw=clean_website(attr(web, "href")) if web else None,
                    city=(text(loc).split(",")[0].strip() if loc else city) or city,
                    founded_year_raw=None,          # profile-page only (see docstring)
                    size_raw=None,                  # profile-page only
                    segment_raw=_opt(text(first(card, SEL_DESCR))),
                )
            )
        return rows


def _opt(v: str) -> Optional[str]:
    return v or None
