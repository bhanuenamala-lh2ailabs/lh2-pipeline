"""Company-site founder lookup — second source (BUILD SPEC §5a).

Light fetch of /about, /team, /leadership and return the leadership text for the
same Claude extraction prompt. Company-site titles are good for *role*; registry
is better for legal ground truth.
"""

from __future__ import annotations

from typing import Optional

from ..crawl.parsing import soup, text
from ..logging_setup import get_logger

log = get_logger("lh2.company_site")

# Team/leadership pages first (most likely to name founders), then about pages.
CANDIDATE_PATHS = [
    "/team", "/leadership", "/our-team", "/management", "/founders",
    "/about-us", "/about", "/company",
]
MAX_TEXT_CHARS = 9000   # cap concatenated text fed to Claude (token budget)


class CompanySiteClient:
    def __init__(self, fetcher=None, timeout_s: int = 20, max_pages: int = 3):  # noqa: ANN001
        self.fetcher = fetcher
        self.timeout_s = timeout_s
        self.max_pages = max_pages

    def _get(self, url: str, ua: str = "LH2Bot/0.1") -> Optional[str]:
        if self.fetcher is None:
            raise RuntimeError("CompanySiteClient needs a fetcher for live access")
        try:
            return self.fetcher.fetch(url, ua, self.timeout_s)
        except Exception as e:
            log.debug("site_fetch_failed", url=url, err=str(e))
            return None

    def leadership_text(self, website: Optional[str]) -> Optional[str]:
        """Concatenate text from up to ``max_pages`` candidate pages (team/leadership
        prioritized) so Claude sees a page that actually names founders, not just the
        first marketing page that happens to have text."""
        if not website:
            return None
        base = website.rstrip("/")
        if "://" not in base:
            base = "https://" + base

        chunks: list[str] = []
        total = 0
        for path in CANDIDATE_PATHS:
            if len(chunks) >= self.max_pages or total >= MAX_TEXT_CHARS:
                break
            html = self._get(base + path)
            if not html:
                continue
            body = soup(html)
            txt = text(body.body if body.body else body)
            if txt and len(txt) > 50:
                chunk = f"[{path}] {txt[:MAX_TEXT_CHARS]}"
                chunks.append(chunk)
                total += len(chunk)
        if not chunks:
            return None
        return ("\n\n".join(chunks))[:MAX_TEXT_CHARS]
