"""Phase 5 tests: exact 14-col schema/order, blank-unless-confirmed LinkedIn rule,
hyperlink wrapping, and the LinkedIn review sheet."""

from __future__ import annotations

import csv

from lh2_pipeline.export.csv_writer import (
    COLUMNS,
    build_rows,
    write_csv,
    write_linkedin_review,
)
from lh2_pipeline.models import Company, Confidence, Person
from lh2_pipeline.store import Store

RESOLVER = "https://www.google.com/search?q={query}"


def _seed(tmp_path):
    s = Store(tmp_path / "x.sqlite")
    s.init_db()
    # passing firm with confirmed-LI primary + SPOC2 without LI
    s.upsert_company(Company(domain="cmarix.com", company_name="CMARIX",
                             website="https://www.cmarix.com", city="Ahmedabad",
                             hq_country="India", founded_year=2013, size_band="50-249",
                             size_source="50-249", segment="Custom software",
                             status="Independent", gate_pass=True,
                             gate_reason="near-250 headcount ceiling"))
    s.upsert_person(Person(domain="cmarix.com", name="Hardik Patel", role="Founder & CEO",
                           name_source="registry", is_primary=True,
                           linkedin_url="https://linkedin.com/in/hardik",
                           linkedin_confirmed=True, phone="+919876543210",
                           phone_source="signalhire", confidence=Confidence.green,
                           notes="sources: registry, company_site"))
    s.upsert_person(Person(domain="cmarix.com", name="Second Founder", role="CTO",
                           name_source="registry", is_primary=False,
                           linkedin_url="https://linkedin.com/in/maybe-wrong",
                           linkedin_confirmed=False, phone="+919999988888",
                           notes="sources: registry; LI tentative (uncertain): namesake"))
    # a non-passing firm must NOT appear
    s.upsert_company(Company(domain="big.com", company_name="Big", gate_pass=False))
    return s


def test_schema_first_14_columns_in_order_then_email(tmp_path):
    # Original 14 columns keep their exact positions; Email is appended (col 15).
    assert len(COLUMNS) == 15
    assert COLUMNS[0] == "#" and COLUMNS[1] == "Company"
    assert COLUMNS[3] == "Founder LinkedIn (verified)"
    assert COLUMNS[4] == "Contact Number" and COLUMNS[6] == "Contact Number"
    assert COLUMNS[5] == "SPOC 2 Linkedin"
    assert COLUMNS[13] == "Notes"          # last of the original 14 — position unchanged
    assert COLUMNS[14] == "Email"          # appended


def test_plain_csv_content_and_rules(tmp_path):
    s = _seed(tmp_path)
    path = tmp_path / "out.csv"
    n = write_csv(s, path, hyperlinked=False, resolver=RESOLVER)
    assert n == 1  # only the gate-passing firm

    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == COLUMNS
    rec = rows[1]
    assert rec[1] == "CMARIX"
    assert rec[2] == "Hardik Patel (Founder & CEO); Second Founder (CTO)"
    # LinkedIn shown when present (confirmed or Signalhire-matched); unverified ones flagged in Notes
    assert rec[3] == "https://linkedin.com/in/hardik"
    assert rec[4] == "+919876543210"
    assert rec[5] == "https://linkedin.com/in/maybe-wrong"   # SPOC 2 LinkedIn now shown
    assert rec[6] == "+919999988888"
    assert rec[7] == "2013"
    assert rec[9] == "50-249"
    assert "near-250" in rec[13]
    s.close()


def test_hyperlinked_company_cell(tmp_path):
    s = _seed(tmp_path)
    rows = build_rows(s, hyperlinked=True, resolver=RESOLVER)
    cell = rows[0][1]
    assert cell.startswith('=HYPERLINK("https://www.cmarix.com","CMARIX")')
    s.close()


def test_hyperlinked_uses_resolver_when_no_website(tmp_path):
    s = Store(tmp_path / "y.sqlite")
    s.init_db()
    s.upsert_company(Company(domain="nosite.com", company_name="No Site Co",
                             website=None, city="Pune", gate_pass=True))
    rows = build_rows(s, hyperlinked=True, resolver=RESOLVER)
    assert "google.com/search" in rows[0][1]
    assert "No+Site+Co" in rows[0][1]
    s.close()


def test_linkedin_review_sheet(tmp_path):
    s = _seed(tmp_path)
    path = tmp_path / "review.csv"
    n = write_linkedin_review(s, path)
    # primary has confirmed LI -> NOT in review sheet
    assert n == 0
    s.close()
