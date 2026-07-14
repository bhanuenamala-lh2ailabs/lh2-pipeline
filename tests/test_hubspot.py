"""Phase 5c tests — HubSpot setup + sync against an injected HTTP responder
(no network). Verifies idempotent property/pipeline creation, qualified-only
selection, upsert idProperty keys, name splitting, and associations."""

from __future__ import annotations

from lh2_pipeline.export.hubspot import (
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    HubspotClient,
    _split_name,
    run_hubspot_setup,
    run_hubspot_sync,
)
from lh2_pipeline.models import Company, Person
from lh2_pipeline.store import Store


class _HS:
    pipeline_source = "TEST-SRC"


class _Sec:
    hubspot_api_key = "tok"


class FakeCfg:
    hubspot = _HS()
    secrets = _Sec()


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def test_setup_creates_all_when_absent():
    posts = []

    def responder(method, path, json):
        if method == "GET" and "/properties/" in path:
            return 404, {}                         # every prop missing → create
        if method == "POST" and path.startswith("/crm/v3/properties/"):
            posts.append(json["name"]); return 201, {}
        if method == "GET" and path.endswith("/pipelines/deals"):
            return 200, {"results": []}            # no pipeline yet
        if method == "POST" and path.endswith("/pipelines/deals"):
            posts.append("PIPELINE"); return 201, {}
        return 200, {}

    r = run_hubspot_setup(FakeCfg(), client=HubspotClient(responder=responder))
    assert len(r["company_props"]) == len(COMPANY_PROPERTIES)
    assert len(r["contact_props"]) == len(CONTACT_PROPERTIES)
    assert r["pipeline"] == "Codebase Acquisition"
    assert "PIPELINE" in posts
    assert "size_bucket" in posts and "spoc_type" in posts


def test_setup_is_idempotent_when_present():
    def responder(method, path, json):
        if method == "GET" and "/properties/" in path:
            return 200, {}                         # everything already exists
        if method == "GET" and path.endswith("/pipelines/deals"):
            return 200, {"results": [{"label": "Codebase Acquisition"}]}
        if method == "POST":
            raise AssertionError("should not create anything when all exist")
        return 200, {}

    r = run_hubspot_setup(FakeCfg(), client=HubspotClient(responder=responder))
    assert r["company_props"] == [] and r["contact_props"] == []
    assert r["pipeline"] is None
    assert len(r["skipped"]) == len(COMPANY_PROPERTIES) + len(CONTACT_PROPERTIES) + 1


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
def _seed(store):
    # qualified (4/4)
    store.upsert_company(Company(domain="acme.com", company_name="Acme Labs", city="Pune",
                                 hq_country="India", founded_year=2016, size_band="50-249",
                                 size_bucket="100-500", segment="Custom software", gate_pass=True))
    store.upsert_person(Person(domain="acme.com", name="Asha Rao", role="Founder & CEO",
                               is_primary=True, linkedin_url="https://linkedin.com/in/asha",
                               phone="+919876543210", email="asha@acme.com"))
    # 3/4 (no email) — must be skipped
    store.upsert_company(Company(domain="bar.com", company_name="Bar", hq_country="India",
                                 founded_year=2019, size_band="10-49", size_bucket="1-100",
                                 gate_pass=True))
    store.upsert_person(Person(domain="bar.com", name="B Founder", is_primary=True,
                               linkedin_url="https://linkedin.com/in/b", phone="+919000000000"))


def test_sync_pushes_only_qualified_with_upsert_keys(tmp_path):
    store = Store(tmp_path / "h.sqlite"); store.init_db()
    _seed(store)
    calls = []

    def responder(method, path, json):
        calls.append((path, json))
        if path.endswith("/companies/search"):
            return 200, {"results": []}            # none exist yet → all created
        if path.endswith("/companies/batch/create"):
            return 200, {"results": [{"id": f"co{i}",
                                     "properties": {"domain": inp["properties"]["domain"]}}
                                     for i, inp in enumerate(json["inputs"])]}
        if path.endswith("/contacts/batch/upsert"):
            return 200, {"results": [{"id": f"ct{i}", "properties": {"email": inp["id"]}}
                                     for i, inp in enumerate(json["inputs"])]}
        if "associate/default" in path:
            return 201, {}
        return 200, {}

    stats = run_hubspot_sync(FakeCfg(), store, client=HubspotClient(responder=responder))
    assert stats["companies"] == 1 and stats["contacts"] == 1 and stats["associations"] == 1

    # company created (search found none), with mapped custom props incl. domain
    co_call = next(j for p, j in calls if p.endswith("/companies/batch/create"))
    ci = co_call["inputs"][0]
    assert ci["properties"]["domain"] == "acme.com"
    assert ci["properties"]["size_bucket"] == "100-500"
    assert ci["properties"]["founded_year"] == 2016
    assert ci["properties"]["pipeline_source"] == "TEST-SRC"

    # contact upsert keyed on email, name split, spoc_type Primary
    ct_call = next(j for p, j in calls if p.endswith("/contacts/batch/upsert"))
    cti = ct_call["inputs"][0]
    assert cti["idProperty"] == "email" and cti["id"] == "asha@acme.com"
    assert cti["properties"]["firstname"] == "Asha" and cti["properties"]["lastname"] == "Rao"
    assert cti["properties"]["spoc_type"] == "Primary"

    # association pairs contact ct0 -> company co0
    assoc = next(j for p, j in calls if "associate/default" in p)
    assert assoc["inputs"] == [{"from": {"id": "ct0"}, "to": {"id": "co0"}}]
    store.close()


def test_sync_dry_run_pushes_nothing(tmp_path):
    store = Store(tmp_path / "h2.sqlite"); store.init_db()
    _seed(store)

    def responder(method, path, json):
        raise AssertionError("dry-run must not call HubSpot")

    stats = run_hubspot_sync(FakeCfg(), store, client=HubspotClient(responder=responder),
                             dry_run=True)
    assert stats["companies"] == 1 and stats["dry_run"] is True
    store.close()


def test_split_name():
    assert _split_name("Asha Rao") == ("Asha", "Rao")
    assert _split_name("Madonna") == ("Madonna", "")
    assert _split_name("A B C") == ("A", "B C")
    assert _split_name("") == ("", "")
