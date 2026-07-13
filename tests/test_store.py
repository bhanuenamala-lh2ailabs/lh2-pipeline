"""Phase 2 (model) DoD: migrations create tables; typed upsert + cache round-trip."""

from __future__ import annotations

from lh2_pipeline.models import Company, Confidence, Person, RawListing
from lh2_pipeline.store import Store


def _store(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.init_db()
    return s


def test_migrations_create_tables(tmp_path):
    s = _store(tmp_path)
    counts = s.counts()
    assert set(counts) >= {"raw_listings", "companies", "people", "cache"}
    assert all(v == 0 for k, v in counts.items())
    s.close()


def test_company_and_person_round_trip(tmp_path):
    s = _store(tmp_path)
    s.upsert_company(
        Company(
            domain="cmarix.com",
            company_name="CMARIX",
            website="https://www.cmarix.com",
            city="Ahmedabad",
            hq_country="India",
            founded_year=2013,
            size_band="50-249",
            gate_pass=True,
            sources_json=[{"source": "goodfirms", "url": "https://x"}],
        )
    )
    s.upsert_person(
        Person(
            domain="cmarix.com",
            name="Hardik Patel",
            role="Founder & CEO",
            name_source="registry",
            is_primary=True,
            confidence=Confidence.green,
        )
    )

    co = s.get_company("cmarix.com")
    assert co is not None
    assert co.company_name == "CMARIX"
    assert co.gate_pass is True
    assert co.sources_json[0]["source"] == "goodfirms"

    people = s.people_for("cmarix.com")
    assert len(people) == 1
    assert people[0].name == "Hardik Patel"
    assert people[0].is_primary is True
    assert people[0].confidence == Confidence.green
    s.close()


def test_upsert_is_idempotent(tmp_path):
    s = _store(tmp_path)
    for _ in range(3):
        s.upsert_company(Company(domain="dup.com", company_name="Dup"))
        s.upsert_person(Person(domain="dup.com", name="Jane Doe", is_primary=True))
    assert s.counts()["companies"] == 1
    assert s.counts()["people"] == 1
    s.close()


def test_cache_get_set_write_through(tmp_path):
    s = _store(tmp_path)
    assert s.cache_get("signalhire:cmarix.com") is None
    assert s.cache_has("signalhire:cmarix.com") is False
    s.cache_set("signalhire:cmarix.com", {"phone": "+919876543210"})
    assert s.cache_has("signalhire:cmarix.com") is True
    assert s.cache_get("signalhire:cmarix.com")["phone"] == "+919876543210"
    s.close()


def test_raw_listing_insert_and_iter(tmp_path):
    s = _store(tmp_path)
    s.insert_raw_listing(
        RawListing(
            source="goodfirms",
            source_url="https://goodfirms.co/x",
            company_name="Acme",
            city="Pune",
            website_raw="acme.io",
        )
    )
    # idempotent on (source, source_url, company_name)
    s.insert_raw_listing(
        RawListing(
            source="goodfirms",
            source_url="https://goodfirms.co/x",
            company_name="Acme",
            city="Pune",
            website_raw="acme.io",
        )
    )
    rows = list(s.iter_raw_listings())
    assert len(rows) == 1
    assert rows[0].company_name == "Acme"
    s.close()
