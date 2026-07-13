"""Tests for the rate-limit + quota safety layer, the net-new exclusion loader,
SignalHire email extraction, and the enrich loop's clean stop on quota exhaustion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lh2_pipeline.config import GatesConfig, JudgeConfig
from lh2_pipeline.enrich import run_enrich
from lh2_pipeline.enrich.signalhire import SignalhireClient
from lh2_pipeline.governor import Governor
from lh2_pipeline.models import Company
from lh2_pipeline.quota_ledger import QuotaExceeded, QuotaLedger, window_key
from lh2_pipeline.ratelimit import RateLimiter
from lh2_pipeline.store import Store
from lh2_pipeline.transform.exclusions import load_exclusions


# --------------------------------------------------------------------------- #
# Rate limiter (fake clock — never actually sleeps)
# --------------------------------------------------------------------------- #
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_ratelimiter_paces_to_the_rate():
    fc = FakeClock()
    rl = RateLimiter(per_second=1, safety_margin=1.0, clock=fc.now, sleep=fc.sleep)
    assert rl.acquire() == 0.0          # bucket starts full → first is free
    assert rl.acquire() == 1.0          # must wait 1s for one token to refill
    fc.t += 5                            # idle long enough to refill
    assert rl.acquire() == 0.0


def test_ratelimiter_safety_margin_slows_it():
    fc = FakeClock()
    # 60/min at 50% margin = 30/min = 1 token / 2s
    rl = RateLimiter(per_minute=60, safety_margin=0.5, clock=fc.now, sleep=fc.sleep)
    for _ in range(30):                 # drain the safety-margined capacity (30)
        rl.acquire()
    assert rl.acquire() == pytest.approx(2.0)


def test_ratelimiter_unlimited_when_no_limits():
    rl = RateLimiter()
    assert rl.unlimited is True
    assert rl.acquire() == 0.0


# --------------------------------------------------------------------------- #
# Quota ledger (persistent, safety-margined, window-reset)
# --------------------------------------------------------------------------- #
def _fixed(day=13):
    return lambda: datetime(2026, 7, day, tzinfo=timezone.utc)


def test_quota_ledger_charges_and_caps(tmp_path):
    s = Store(tmp_path / "q.sqlite")
    s.init_db()
    led = QuotaLedger(s, "signalhire", {"search_per_day": 100},
                      reset="daily_utc", safety_margin=0.8, now_fn=_fixed())
    assert led.effective_limit("search") == 80      # 100 * 0.8
    assert led.remaining("search") == 80
    for _ in range(80):
        led.charge("search")
    assert led.remaining("search") == 0
    assert led.would_exceed("search") is True
    with pytest.raises(QuotaExceeded):
        led.charge("search")
    s.close()


def test_quota_ledger_resets_across_days(tmp_path):
    s = Store(tmp_path / "q2.sqlite")
    s.init_db()
    limits = {"search_per_day": 100}
    QuotaLedger(s, "sh", limits, safety_margin=1.0, now_fn=_fixed(13)).charge("search", 50)
    # a new UTC day is a fresh window → full quota again
    day2 = QuotaLedger(s, "sh", limits, safety_margin=1.0, now_fn=_fixed(14))
    assert day2.remaining("search") == 100
    s.close()


def test_quota_ledger_uncapped_metric_is_none(tmp_path):
    s = Store(tmp_path / "q3.sqlite")
    s.init_db()
    led = QuotaLedger(s, "sh", {}, now_fn=_fixed())
    assert led.effective_limit("search") is None
    assert led.remaining("search") is None
    assert led.would_exceed("search", 999) is False   # never blocks when uncapped
    s.close()


def test_window_key_formats():
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    assert window_key("daily_utc", now) == "2026-07-13"
    assert window_key("monthly", now) == "2026-07"
    assert window_key("none", now) == "all"


# --------------------------------------------------------------------------- #
# Governor
# --------------------------------------------------------------------------- #
def test_governor_stops_at_cap(tmp_path):
    s = Store(tmp_path / "g.sqlite")
    s.init_db()
    led = QuotaLedger(s, "p", {"search_per_day": 2}, safety_margin=1.0, now_fn=_fixed())
    g = Governor("p", RateLimiter(), led)
    g.pace()                       # unlimited rate → no-op
    g.check_and_charge("search")
    g.check_and_charge("search")
    with pytest.raises(QuotaExceeded):
        g.check_and_charge("search")
    s.close()


# --------------------------------------------------------------------------- #
# Net-new exclusion loader
# --------------------------------------------------------------------------- #
class _FakeCfg:
    def __init__(self, root: Path, gates: GatesConfig):
        self.project_root = root
        self.gates = gates

    def abspath(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def test_exclusions_harvest_names_and_domains(tmp_path):
    # A delivery CSV: HYPERLINK company (domain embedded) + a plain-name row.
    (tmp_path / "delivered.csv").write_text(
        '#,Company,Notes\n'
        '1,"=HYPERLINK(""https://foo.com/"",""Foo Labs"")",x\n'
        '2,Bar Technologies,y\n',
        encoding="utf-8",
    )
    # An AI-Labs style CSV with an explicit Domain column.
    (tmp_path / "ailabs.csv").write_text(
        "Company Name,Domain Name\nApplane,applane.com\n", encoding="utf-8"
    )
    # A one-domain-per-line delivered file (with a comment + blank).
    (tmp_path / "dom.txt").write_text("baz.io\n# note\n\n", encoding="utf-8")

    gates = GatesConfig(
        blocklist_known_file=None,
        exclude_name_files=["delivered.csv", "ailabs.csv"],
        exclude_domain_files=["dom.txt"],
    )
    ex = load_exclusions(_FakeCfg(tmp_path, gates))

    assert {"foo.com", "applane.com", "baz.io"} <= ex.domains
    names_lower = {n.lower() for n in ex.names}
    assert "foo labs" in names_lower           # unwrapped from HYPERLINK display
    assert "bar technologies" in names_lower
    assert "applane" in names_lower


def test_exclusions_missing_file_is_skipped(tmp_path):
    gates = GatesConfig(blocklist_known_file=None,
                        exclude_name_files=["does_not_exist.csv"])
    ex = load_exclusions(_FakeCfg(tmp_path, gates))
    assert ex.names == [] and ex.domains == set()


# --------------------------------------------------------------------------- #
# SignalHire email extraction (work email preferred)
# --------------------------------------------------------------------------- #
def test_signalhire_extracts_email_work_first():
    def responder(path, payload):
        if path.endswith("searchByQuery"):
            return {"profiles": [{"fullName": "Hardik Patel", "uid": "ABC",
                                  "experience": [{"company": "CMARIX", "title": "Founder"}]}]}
        return [{"item": "ABC", "status": "success", "candidate": {"contacts": [
            {"type": "email", "value": "personal@gmail.com"},
            {"type": "email", "subType": "work", "value": "hardik@cmarix.com"},
            {"type": "phone", "value": "9876543210"},
        ]}}]

    sh = SignalhireClient(responder=responder)
    c = sh.contact_for_person("Hardik Patel", "CMARIX")
    assert c["emails"][0] == "hardik@cmarix.com"        # work email ranked first
    assert "personal@gmail.com" in c["emails"]
    assert c["phones"] == ["+919876543210"]


# --------------------------------------------------------------------------- #
# Enrich loop stops cleanly when the SignalHire search quota is exhausted
# --------------------------------------------------------------------------- #
def _cfg():
    class C:
        class enrich:
            max_enrich = 100
        judge = JudgeConfig()
    return C()


def test_enrich_stops_on_quota_exhaustion(tmp_path):
    store = Store(tmp_path / "e.sqlite")
    store.init_db()
    for i in range(3):
        store.upsert_company(Company(domain=f"co{i}.com", company_name=f"Co{i} Labs",
                                     city="Pune", founded_year=2015, size_band="10-49",
                                     gate_pass=True))

    def sh_responder(path, payload):
        # founder title-search returns a founder WITH uid (so no name-search later)
        if path.endswith("searchByQuery"):
            comp = payload.get("currentCompany", "")
            return {"profiles": [{"fullName": "A Founder", "uid": "U",
                                  "experience": [{"company": comp, "title": "Founder"}]}]}
        return [{"item": "U", "status": "success",
                 "candidate": {"contacts": [{"type": "phone", "value": "9876543210"}]}}]

    # cap = 2 searches (safety 1.0) → 3rd firm's founder-search trips QuotaExceeded
    led = QuotaLedger(store, "signalhire", {"search_per_day": 2},
                      safety_margin=1.0, now_fn=_fixed())
    gov = Governor("signalhire", RateLimiter(), led)
    clients = {
        "fetcher": None, "claude": None, "registry": None, "company_site": None,
        "signalhire": SignalhireClient(responder=sh_responder, governor=gov),
        "linkedin": None,
    }

    stats = run_enrich(_cfg(), store, clients=clients)
    assert stats["quota_reached"] is True
    assert stats["enriched"] == 2                 # stopped before the 3rd firm
    assert store.people_for("co2.com") == []      # untouched
    store.close()
