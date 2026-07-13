"""Phase 2 tests: canonicalize, dedupe (multi-source -> one row), gate filter."""

from __future__ import annotations

from lh2_pipeline.config import GatesConfig
from lh2_pipeline.models import Company, RawListing
from lh2_pipeline.transform.canonicalize import (
    canonical_domain,
    normalize_founded,
    normalize_size,
    size_bucket,
    size_headcount,
)
from lh2_pipeline.transform.dedupe import dedupe
from lh2_pipeline.transform.gates import apply_gates


# --- canonicalize ---------------------------------------------------------- #
def test_canonical_domain():
    assert canonical_domain("https://www.CMARIX.com/services?x=1") == "cmarix.com"
    assert canonical_domain("acme.io") == "acme.io"
    assert canonical_domain("http://sub.example.co.uk/path") == "example.co.uk"
    assert canonical_domain("") is None
    assert canonical_domain(None) is None
    assert canonical_domain("not a url") is None


def test_normalize_founded():
    assert normalize_founded("2015").year == 2015
    assert normalize_founded("since 2015").year == 2015
    assert normalize_founded("Founded 2013").year == 2013
    r = normalize_founded("11+ years", reference_year=2026)
    assert r.year == 2015 and r.approximate is True
    r2 = normalize_founded("two decades", reference_year=2026)
    assert r2.year == 2006 and r2.approximate is True
    assert normalize_founded("").year is None


def test_normalize_size():
    assert normalize_size("50 - 249") == "50-249"
    assert normalize_size("10 to 49 employees") == "10-49"
    assert normalize_size("1,000+") == "250+"
    assert normalize_size("Freelancer (1)") == "<10"
    assert normalize_size(None) is None


def test_size_headcount_midpoint():
    assert size_headcount("50 - 249") == 149      # midpoint of the range
    assert size_headcount("250 - 999") == 624
    assert size_headcount("10 - 49") == 29
    assert size_headcount("300") == 300           # single number
    assert size_headcount("10000+") == 10000
    assert size_headcount(None, "50-249") == 150  # band-midpoint fallback
    assert size_headcount(None, None) is None


def test_size_bucket_assignment():
    assert size_bucket("2 - 9") == "1-100"
    assert size_bucket("10 - 49") == "1-100"
    assert size_bucket("50 - 249") == "100-500"   # midpoint 149
    assert size_bucket("250 - 999") == "500-1000" # midpoint 624
    assert size_bucket("1,000 - 9,999") is None   # > 1000 -> out of range
    assert size_bucket("10000+") is None
    assert size_bucket(None, None) is None


# --- dedupe ---------------------------------------------------------------- #
def test_multi_source_firm_collapses_to_one_row():
    raw = [
        RawListing(source="goodfirms", source_url="g1", company_name="CMARIX",
                   website_raw="https://www.cmarix.com", city="Ahmedabad",
                   founded_year_raw="2013", size_raw="50-249"),
        RawListing(source="clutch", source_url="c1", company_name="CMARIX TechnoLabs",
                   website_raw="http://cmarix.com/about", city="Ahmedabad"),
        RawListing(source="techbehemoths", source_url="t1", company_name="CMARIX",
                   website_raw="cmarix.com"),
    ]
    res = dedupe(raw)
    assert len(res.companies) == 1
    co = res.companies["cmarix.com"]
    assert co.founded_year == 2013
    assert co.size_band == "50-249"
    assert len(co.sources_json) == 3
    assert {s["source"] for s in co.sources_json} == {"goodfirms", "clutch", "techbehemoths"}


def test_no_domain_listings_bucketed():
    raw = [RawListing(source="goodfirms", source_url="g", company_name="NoSite Co",
                      website_raw=None, city="Pune")]
    res = dedupe(raw)
    assert len(res.companies) == 0
    assert len(res.no_domain) == 1


# --- gates ----------------------------------------------------------------- #
def _gates(**kw):
    base = dict(
        hq_country="India",
        founded_max_year=2022,
        size_bands_include=["10-49", "50-249"],
        size_bands_exclude=["<10", "250+"],
        blocklist_outsourcers=["Infosys", "TCS", "Wipro"],
        blocklist_known_domains=["known.com"],
    )
    base.update(kw)
    return GatesConfig(**base)


def test_gate_passes_qualifying_firm():
    co = Company(domain="cmarix.com", company_name="CMARIX", founded_year=2013,
                 size_band="50-249")
    out = apply_gates(co, _gates())
    assert out.passed is True
    assert co.gate_pass is True


def test_gate_admits_300_employee_firm_now():
    # widened gate: 300 employees -> bucket 100-500 -> admitted (<=1000)
    co = Company(domain="mid.com", company_name="Mid Co", founded_year=2010,
                 size_band="250+", size_source="300")
    out = apply_gates(co, _gates())
    assert out.passed is True
    assert co.size_bucket == "100-500"


def test_gate_excludes_over_1000_firm():
    co = Company(domain="big.com", company_name="Big Co", founded_year=2010,
                 size_band="250+", size_source="1000 - 9999")
    out = apply_gates(co, _gates())
    assert out.passed is False
    assert co.size_bucket is None
    assert any("above ceiling" in r for r in out.reasons)


def test_gate_excludes_outsourcer_and_too_new_and_known():
    co1 = Company(domain="infy.com", company_name="Infosys Limited",
                  founded_year=1981, size_band="50-249")
    assert apply_gates(co1, _gates()).passed is False

    co2 = Company(domain="new.com", company_name="New Co", founded_year=2024,
                  size_band="10-49")
    out2 = apply_gates(co2, _gates())
    assert out2.passed is False and any("2024" in r for r in out2.reasons)

    co3 = Company(domain="known.com", company_name="Known", founded_year=2015,
                  size_band="10-49")
    assert apply_gates(co3, _gates()).passed is False


def test_known_firm_exclusion_by_core_name():
    from lh2_pipeline.transform.gates import matches_known_firm
    known = ["Velotio Technologies", "Antino (Antino Labs)", "Codewave Technologies"]
    # same firm, different legal suffix -> excluded
    assert matches_known_firm("Velotio Technologies Pvt Ltd", known)
    assert matches_known_firm("Antino Labs", known)
    # net-new firm that merely shares a generic suffix -> NOT excluded
    assert matches_known_firm("Brightline Technologies", known) is None
    assert matches_known_firm("Codeforge Solutions", known) is None


def test_gate_excludes_known_firm_via_param():
    co = Company(domain="velotio.com", company_name="Velotio Technologies Pvt Ltd",
                 founded_year=2016, size_band="50-249")
    out = apply_gates(co, _gates(), known_names=["Velotio Technologies"])
    assert out.passed is False
    assert any("already-known" in r for r in out.reasons)


def test_gate_unknown_fields_fail_closed():
    co = Company(domain="x.com", company_name="X", founded_year=None, size_band=None)
    out = apply_gates(co, _gates())
    assert out.passed is False
    assert "founded year unknown" in out.reasons
    assert "size unknown" in out.reasons


def test_gate_near_ceiling_note():
    # headcount within 10% of the 1000 ceiling -> flagged
    co = Company(domain="edge.com", company_name="Edge", founded_year=2018,
                 size_band="250+", size_source="900 - 999")
    out = apply_gates(co, _gates())
    assert out.passed is True
    assert co.size_bucket == "500-1000"
    assert any("near 1000" in n for n in out.notes)


def test_gate_mid_range_does_not_trigger_near_ceiling():
    co = Company(domain="band.com", company_name="Band Co", founded_year=2018,
                 size_band="50-249", size_source="50 - 249")
    out = apply_gates(co, _gates())
    assert out.passed is True
    assert co.size_bucket == "100-500"          # midpoint 149
    assert not any("near" in n for n in out.notes)
