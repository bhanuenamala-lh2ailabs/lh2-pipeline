"""Phase 5c tests — HubSpot setup + sync against an injected HTTP responder
(no network). Verifies idempotent property/pipeline creation, qualified-only
selection, upsert idProperty keys, name splitting, and associations."""

from __future__ import annotations

from lh2_pipeline.export.hubspot import (
    CALL_FEEDBACK_PROPERTIES,
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    DEAL_PROPERTIES,
    HubspotClient,
    _split_name,
    run_hubspot_setup,
    run_hubspot_sync,
)

_N_CONTACT_PROPS = len(CONTACT_PROPERTIES) + len(CALL_FEEDBACK_PROPERTIES)

# Fake pipeline the sync/workflow tests resolve stage ids from.
FAKE_PIPELINE = {"results": [{"id": "pipe1", "label": "Codebase Acquisition", "stages": [
    {"id": "s-new", "label": "New Lead"},
    {"id": "s-attempted", "label": "Call Attempted"},
    {"id": "s-m1v1", "label": "M1V1 Sent"},
    {"id": "s-m1v2", "label": "M1V2 Sent"},
    {"id": "s-dead-rej", "label": "Dead - Rejected"},
    {"id": "s-dead-nr", "label": "Dead - No Response"},
]}]}
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
    assert len(r["contact_props"]) == _N_CONTACT_PROPS
    assert len(r["deal_props"]) == len(DEAL_PROPERTIES)
    assert r["pipeline"] == "Codebase Acquisition"
    assert r["pipeline_action"] == "created"
    assert "PIPELINE" in posts
    assert "size_bucket" in posts and "spoc_type" in posts
    assert "script_status" in posts and "callback_datetime" in posts   # deal props
    # templates are documented (no API on this tier) — loudly, never silently
    assert r["templates"] == {"M1V1": "manual", "M1V2": "manual"}


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
    assert r["company_props"] == [] and r["contact_props"] == [] and r["deal_props"] == []
    assert r["pipeline"] is None
    assert len(r["skipped"]) == len(COMPANY_PROPERTIES) + _N_CONTACT_PROPS + len(DEAL_PROPERTIES) + 1


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
        calls.append((method, path, json))
        if path == "/crm/v3/pipelines/deals":
            return 200, FAKE_PIPELINE
        if path.endswith("/companies/batch/upsert"):
            return 200, {"results": [{"id": f"co{i}",
                                     "properties": {"lh2_domain": inp["id"]}}
                                     for i, inp in enumerate(json["inputs"])]}
        if path.endswith("/contacts/batch/upsert"):
            return 200, {"results": [{"id": f"ct{i}", "properties": {"email": inp["id"]}}
                                     for i, inp in enumerate(json["inputs"])]}
        if path.endswith("/deals/search"):
            return 200, {"results": []}          # no deals yet → create
        if path.endswith("/deals/batch/create"):
            return 201, {"results": [{"id": f"dl{i}",
                                     "properties": {"lh2_domain": inp["properties"]["lh2_domain"]}}
                                     for i, inp in enumerate(json["inputs"])]}
        if "associate/default" in path:
            return 201, {}
        return 200, {}

    stats = run_hubspot_sync(FakeCfg(), store, client=HubspotClient(responder=responder))
    assert stats["companies"] == 1 and stats["contacts"] == 1
    assert stats["associations"] == 1 and stats["deals"] == 1

    # company upserted by the unique lh2_domain key, with mapped custom props
    co_call = next(j for m, p, j in calls if p.endswith("/companies/batch/upsert"))
    ci = co_call["inputs"][0]
    assert ci["idProperty"] == "lh2_domain" and ci["id"] == "acme.com"
    assert ci["properties"]["lh2_domain"] == "acme.com"
    assert ci["properties"]["size_bucket"] == "100-500"
    assert ci["properties"]["founded_year"] == 2016
    assert ci["properties"]["pipeline_source"] == "TEST-SRC"

    # contact upsert keyed on email, name split, spoc_type Primary
    ct_call = next(j for m, p, j in calls if p.endswith("/contacts/batch/upsert"))
    cti = ct_call["inputs"][0]
    assert cti["idProperty"] == "email" and cti["id"] == "asha@acme.com"
    assert cti["properties"]["firstname"] == "Asha" and cti["properties"]["lastname"] == "Rao"
    assert cti["properties"]["spoc_type"] == "Primary"

    # deal created at "New Lead" (stage ID not label) with the spec's defaults
    dl_call = next(j for m, p, j in calls if p.endswith("/deals/batch/create"))
    dli = dl_call["inputs"][0]["properties"]
    assert dli["dealname"] == "Acme Labs - Codebase Acquisition"
    assert dli["pipeline"] == "pipe1" and dli["dealstage"] == "s-new"
    assert dli["lead_source"] == "LH2 Pipeline"
    assert dli["email_version_sent"] == "None"
    assert dli["call_attempt_count"] == 0 and dli["script_status"] == "Not Started"

    # associations: contact→company, deal→company, deal→contact
    assoc_paths = [p for m, p, j in calls if "associate/default" in p]
    assert any("contacts/companies" in p for p in assoc_paths)
    assert any("deals/companies" in p for p in assoc_paths)
    assert any("deals/contacts" in p for p in assoc_paths)
    store.close()


def test_sync_skips_existing_deals_and_never_updates_them(tmp_path):
    """A firm that already has a deal gets NO deal write at all — the deal's
    stage belongs to sales and must never be dragged back to New Lead."""
    store = Store(tmp_path / "h3.sqlite"); store.init_db()
    _seed(store)
    deal_writes = []

    def responder(method, path, json):
        if path == "/crm/v3/pipelines/deals":
            return 200, FAKE_PIPELINE
        if path.endswith("/companies/batch/upsert"):
            return 200, {"results": [{"id": "co0", "properties": {"lh2_domain": "acme.com"}}]}
        if path.endswith("/contacts/batch/upsert"):
            return 200, {"results": [{"id": "ct0", "properties": {"email": "asha@acme.com"}}]}
        if path.endswith("/deals/search"):
            return 200, {"results": [{"id": "dl-existing", "properties": {"lh2_domain": "acme.com"}}]}
        if "/deals/" in path and method in ("POST", "PATCH") and "search" not in path:
            deal_writes.append(path)
            return 201, {"results": []}
        if "associate/default" in path:
            return 201, {}
        return 200, {}

    stats = run_hubspot_sync(FakeCfg(), store, client=HubspotClient(responder=responder))
    assert stats["deals"] == 0
    assert deal_writes == []                 # existing deal untouched
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


def test_pull_stores_only_touched_feedback(tmp_path):
    from lh2_pipeline.export.hubspot import run_hubspot_pull
    store = Store(tmp_path / "hp.sqlite"); store.init_db()
    _seed(store)  # acme.com founder = asha@acme.com ; bar.com founder = (no email)

    def responder(method, path, json):
        if path.endswith("/contacts/search"):
            return 200, {"results": [
                {"id": "1", "properties": {"email": "asha@acme.com", "call_outcome": "Interested",
                                           "call_notes": "keen, follow up next week", "call_date": "2026-07-15"}},
                {"id": "2", "properties": {"email": "someone@other.com", "call_outcome": "Not Called"}},
            ]}
        raise AssertionError(f"unexpected {method} {path}")

    stats = run_hubspot_pull(FakeCfg(), store, client=HubspotClient(responder=responder))
    assert stats["contacts_scanned"] == 2
    assert stats["feedback_pulled"] == 1                 # the "Not Called" row is ignored
    assert stats["outcomes"] == {"Interested": 1}

    row = store._conn.execute(
        "SELECT domain, call_outcome, call_notes FROM crm_feedback WHERE email='asha@acme.com'").fetchone()
    assert row["domain"] == "acme.com"                   # keyed back to the company
    assert row["call_outcome"] == "Interested"
    assert "follow up" in row["call_notes"]
    store.close()


def test_split_name():
    assert _split_name("Asha Rao") == ("Asha", "Rao")
    assert _split_name("Madonna") == ("Madonna", "")
    assert _split_name("A B C") == ("A", "B C")
    assert _split_name("") == ("", "")
