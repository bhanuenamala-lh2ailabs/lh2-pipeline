"""Registry (MCA/ZaubaCorp) founder lookup — authoritative source.

ZaubaCorp is Cloudflare-class → route fetches through the Playwright fetcher.
The exact search/profile URL structure is wired by the operator per the live
site (do NOT assume an endpoint). For tests, inject a ``fetcher`` with a
``fetch(url, ua, timeout) -> html`` method (same Protocol as crawl.base.Fetcher).

This module returns the *raw director/leadership text*; structured extraction is
done by judge.extract (Claude). Registry is legal ground truth and beats
aggregators (enforced in judge.confidence).
"""

from __future__ import annotations

from typing import Optional

from ..crawl.parsing import soup, text
from ..logging_setup import get_logger

log = get_logger("lh2.registry")

DEFAULT_BASE = "https://www.zaubacorp.com"
# Operator confirms the live search path; documented placeholder:
SEARCH_PATH = "/companysearchresults/{query}"

# Selector for the directors/signatories block — isolated for easy fixing.
SEL_DIRECTOR_BLOCK = "#directors, .directors, table#table"


class RegistryClient:
    def __init__(self, fetcher=None, base_url: str = DEFAULT_BASE, timeout_s: int = 45):  # noqa: ANN001
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _get(self, url: str, ua: str = "LH2Bot/0.1") -> str:
        if self.fetcher is None:
            raise RuntimeError(
                "RegistryClient needs a Playwright fetcher for live ZaubaCorp access"
            )
        return self.fetcher.fetch(url, ua, self.timeout_s)

    def director_text(self, company_name: str, city: Optional[str] = None) -> Optional[str]:
        """Best-effort: fetch the company's registry profile and return the
        directors/leadership text block for Claude to parse. Returns None if not
        found (caller leaves founder as '(verify)')."""
        query = company_name.strip().replace(" ", "-").lower()
        url = self.base_url + SEARCH_PATH.format(query=query)
        try:
            html = self._get(url)
        except Exception as e:
            log.info("registry_fetch_failed", company=company_name, err=str(e))
            return None
        s = soup(html)
        block = s.select_one(SEL_DIRECTOR_BLOCK)
        txt = text(block) if block else text(s.body if s.body else s)
        return txt or None
