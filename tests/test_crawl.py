"""Crawler infra tests (offline, deterministic) + parser-logic test.

Note: these verify the *plumbing* (cache, retry, block-detect, robots, UA
rotation) and the parser logic against a fixture whose DOM matches the isolated
selectors. They do NOT confirm the live-site selectors — that is what the
`lh2 smoke <source>` gate does once Playwright + network are available.
"""

from __future__ import annotations

import pytest

from lh2_pipeline.crawl.base import (
    BaseCrawler,
    BlockedError,
    CrawlSettings,
    FetchError,
    looks_blocked,
)
from lh2_pipeline.crawl.goodfirms import GoodFirmsCrawler


class FakeFetcher:
    def __init__(self, html="<html>ok</html>", fail_times=0):
        self.html = html
        self.fail_times = fail_times
        self.calls = 0
        self.uas: list[str] = []

    def fetch(self, url, user_agent, timeout_s):
        self.calls += 1
        self.uas.append(user_agent)
        if self.calls <= self.fail_times:
            raise RuntimeError("transient boom")
        return self.html


def _settings(tmp_path, **kw):
    base = dict(
        raw_html_dir=tmp_path / "raw",
        user_agents=["UA-A", "UA-B"],
        delay_min_s=0,
        delay_max_s=0,
        retry_attempts=3,
        honor_robots=False,
        sleep=lambda s: None,          # no real sleeping
        jitter=lambda a, b: a,         # deterministic
        ua_pick=lambda uas: uas[0],    # deterministic UA
    )
    base.update(kw)
    return CrawlSettings(**base)


class _Dummy(BaseCrawler):
    source = "dummy"

    def city_urls(self, city):
        return [f"https://example.test/{city}/1"]

    def parse(self, html, url, city):
        return []


def test_cache_hit_skips_second_fetch(tmp_path):
    f = FakeFetcher(html="<html>page</html>")
    c = _Dummy(f, _settings(tmp_path))
    url = "https://example.test/x"
    assert c.get(url) == "<html>page</html>"
    assert f.calls == 1
    # second call served from gzip cache
    assert c.get(url) == "<html>page</html>"
    assert f.calls == 1


def test_refresh_bypasses_cache(tmp_path):
    f = FakeFetcher(html="<html>page</html>")
    c = _Dummy(f, _settings(tmp_path))
    url = "https://example.test/y"
    c.get(url)
    c.get(url, refresh=True)
    assert f.calls == 2


def test_block_detection_raises(tmp_path):
    assert looks_blocked("<html>Just a moment...</html>") is True
    f = FakeFetcher(html="<title>Attention Required! | Cloudflare</title>")
    c = _Dummy(f, _settings(tmp_path))
    with pytest.raises(BlockedError):
        c.get("https://example.test/blocked")


def test_retry_then_success(tmp_path):
    f = FakeFetcher(html="<html>ok</html>", fail_times=2)
    c = _Dummy(f, _settings(tmp_path, retry_attempts=3))
    assert c.get("https://example.test/retry") == "<html>ok</html>"
    assert f.calls == 3


def test_retry_exhausted_raises(tmp_path):
    f = FakeFetcher(html="<html>ok</html>", fail_times=5)
    c = _Dummy(f, _settings(tmp_path, retry_attempts=2))
    with pytest.raises(FetchError):
        c.get("https://example.test/fail")


def test_robots_disallow(tmp_path):
    f = FakeFetcher()
    c = _Dummy(f, _settings(tmp_path, honor_robots=True))

    # force a robots parser that disallows everything
    class _RP:
        def can_fetch(self, ua, url):
            return False

    c._robots["https://example.test"] = _RP()  # type: ignore
    with pytest.raises(BlockedError):
        c.get("https://example.test/nope")


# --- parser-logic test on a fixture mirroring the CONFIRMED live DOM -------- #
GOODFIRMS_FIXTURE = """
<html><body>
  <ul class="firm-directory-list">
    <li class="firm-wrapper" entity-name="Acme Software Pvt Ltd">
      <div class="firm-header-wrapper">
        <h3 class="firm-name"><a href="/company/acme">Acme Software Pvt Ltd</a></h3>
      </div>
      <p class="firm-short-description">Custom software development</p>
      <div class="firm-employees"><i></i><span>50 - 249</span></div>
      <div class="firm-founded"><i></i><span>2015</span></div>
      <div class="firm-location"><i></i><span>Pune, India</span></div>
      <div class="firm-urls full-firm-url">
        <a href="https://acme.example.com/" class="visit-website">Visit Website</a>
      </div>
    </li>
    <li class="firm-wrapper" entity-name="Globex Technologies">
      <div class="firm-header-wrapper">
        <h3 class="firm-name"><a href="/company/globex">Globex Technologies</a></h3>
      </div>
      <div class="firm-location"><i></i><span>Pune, India</span></div>
    </li>
  </ul>
</body></html>
"""


def test_goodfirms_parser_extracts_rows(tmp_path):
    c = GoodFirmsCrawler(FakeFetcher(), _settings(tmp_path))
    rows = c.parse(GOODFIRMS_FIXTURE, "https://goodfirms.co/x", "Pune")
    assert len(rows) == 2
    a = rows[0]
    assert a.company_name == "Acme Software Pvt Ltd"
    assert a.website_raw == "https://acme.example.com/"
    assert a.city == "Pune, India"
    assert a.founded_year_raw == "2015"
    assert a.size_raw == "50 - 249"
    assert a.source == "goodfirms"
    # missing optional fields stay None (no fabrication)
    assert rows[1].founded_year_raw is None


# --- TechBehemoths parser (selectors confirmed live 2026-07-13) ------------ #
from lh2_pipeline.crawl.techbehemoths import TechBehemothsCrawler

TECHBEHEMOTHS_FIXTURE = """
<html><body>
<div class="co-box">
  <div class="co-box__heading flex">
    <p class="co-box__name font-medium">Magneto IT Solutions
      <span class="verified--ico relative">Verified Company</span></p>
    <p class="co-box__loc"><span class="co-box__loc-itm">Pune , India</span>
      <span class="co-box__loc-itm">Head office in: United States</span></p>
  </div>
  <p class="co-box__descr">Digitally transform B2B and D2C businesses.</p>
  <div class="grid actions"><a class="btn btn-outlined btn-website flex-centered"
     href="https://magnetoitsolutions.com/?utm_source=Tech-Behemoths&utm_medium=Profile">Visit Website</a></div>
</div>
<div class="co-box">
  <div class="co-box__heading flex">
    <p class="co-box__name font-medium">TechGropse Pvt. Ltd.</p>
    <p class="co-box__loc"><span class="co-box__loc-itm">Pune , India</span></p>
  </div>
  <p class="co-box__descr">Mobile app development.</p>
</div>
</body></html>
"""


def test_techbehemoths_parser_extracts_rows(tmp_path):
    c = TechBehemothsCrawler(FakeFetcher(), _settings(tmp_path))
    rows = c.parse(TECHBEHEMOTHS_FIXTURE, "https://techbehemoths.com/companies/pune", "Pune")
    assert len(rows) == 2
    a = rows[0]
    assert a.company_name == "Magneto IT Solutions"          # "Verified Company" badge stripped
    assert a.website_raw.startswith("https://magnetoitsolutions.com/")
    assert a.city == "Pune"                                  # first token of "Pune , India"
    assert a.segment_raw == "Digitally transform B2B and D2C businesses."
    # listing carries no founded/size -> stay None (need profile-page fetch)
    assert a.founded_year_raw is None and a.size_raw is None
    # second firm has no website button -> None (not fabricated)
    assert rows[1].company_name == "TechGropse Pvt. Ltd."
    assert rows[1].website_raw is None
