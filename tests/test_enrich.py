"""Phase 3 tests: phones, Signalhire (ignores LinkedIn), founder extract+merge,
run_enrich end-to-end with fakes, and cache idempotency (zero re-calls)."""

from __future__ import annotations

from lh2_pipeline.config import JudgeConfig
from lh2_pipeline.enrich import run_enrich
from lh2_pipeline.enrich.phones import normalize_e164
from lh2_pipeline.enrich.signalhire import SignalhireClient
from lh2_pipeline.judge.claude_client import ClaudeClient
from lh2_pipeline.judge.extract import extract_directors
from lh2_pipeline.models import Company
from lh2_pipeline.store import Store


# --- phones ---------------------------------------------------------------- #
def test_normalize_e164():
    assert normalize_e164("9876543210") == "+919876543210"
    assert normalize_e164("09876543210") == "+919876543210"
    assert normalize_e164("+91 98765 43210") == "+919876543210"
    assert normalize_e164("0091-9876543210") == "+919876543210"
    assert normalize_e164("12345") is None          # too short → no guess
    assert normalize_e164(None) is None


# --- Signalhire 2-step (search -> enrich), ignores LinkedIn ----------------- #
def test_signalhire_search_then_enrich_phones_ignores_linkedin():
    def responder(path, payload):
        if path.endswith("searchByQuery"):
            return {"profiles": [{"fullName": "Hardik Patel", "uid": "ABC123",
                                  "experience": [{"company": "CMARIX", "title": "Founder"}]}]}
        # enrich
        return [{
            "item": "ABC123", "status": "success",
            "candidate": {"fullName": "Hardik Patel", "contacts": [
                {"type": "phone", "value": "9876543210"},
                {"type": "work_phone", "value": "+91 99999 88888"},
                {"type": "email", "value": "h@cmarix.com"},
                {"type": "linkedin", "value": "https://linkedin.com/in/wrong"},
            ]},
        }]

    sh = SignalhireClient(responder=responder)
    phones = sh.fetch_phones_for_person("Hardik Patel", "CMARIX", "Ahmedabad")
    assert phones == ["+919876543210", "+919999988888"]
    assert all("linkedin" not in p and "@" not in p for p in phones)


def test_signalhire_no_match_returns_empty():
    def responder(path, payload):
        if path.endswith("searchByQuery"):
            return {"profiles": []}   # no profile found
        return []
    sh = SignalhireClient(responder=responder)
    assert sh.fetch_phones_for_person("Nobody Here", "Ghost Co") == []


# --- founder extraction ---------------------------------------------------- #
def test_extract_directors_parses_json():
    def responder(system, user, model):
        return '[{"name": "Arpit Jain", "role": "Director"}, {"name": "Indu Jain", "role": "Director"}]'

    c = ClaudeClient(responder=responder)
    people = extract_directors(c, "Promatics Technologies", "Ludhiana", "Board: Arpit Jain, Indu Jain")
    assert [p["name"] for p in people] == ["Arpit Jain", "Indu Jain"]


def test_extract_empty_text_returns_empty():
    c = ClaudeClient(responder=lambda s, u, m: "[]")
    assert extract_directors(c, "X", "Y", "") == []


# --- run_enrich end-to-end with fakes + idempotency ------------------------ #
class FakeRegistry:
    def __init__(self):
        self.calls = 0

    def director_text(self, name, city):
        self.calls += 1
        # Promatics real case: registry founders are Arpit Jain & Indu Jain.
        return "Directors: Arpit Jain (Director); Indu Jain (Director)"


def _seed_company(store):
    store.upsert_company(
        Company(domain="promatics.com", company_name="Promatics Technologies",
                city="Ludhiana", founded_year=2008, size_band="50-249", gate_pass=True)
    )


def _clients(store):
    counters = {"claude": 0, "sh": 0}

    def claude_responder(system, user, model):
        counters["claude"] += 1
        return '[{"name":"Arpit Jain","role":"Director"},{"name":"Indu Jain","role":"Director"}]'

    def sh_responder(path, payload):
        counters["sh"] += 1
        if path.endswith("searchByQuery"):
            if "Arpit" in payload.get("fullName", ""):
                return {"profiles": [{"fullName": "Arpit Jain", "uid": "U1",
                                      "experience": [{"company": payload.get("currentCompany", ""),
                                                      "title": "Director"}]}]}
            return {"profiles": []}  # only Arpit resolves
        # enrich
        if payload.get("items", [None])[0] == "U1":
            return [{"item": "U1", "status": "success",
                     "candidate": {"contacts": [{"type": "phone", "value": "9876543210"}]}}]
        return []

    reg = FakeRegistry()
    clients = {
        "fetcher": None,
        "claude": ClaudeClient(responder=claude_responder, store=store),
        "registry": reg,
        "company_site": None,
        "signalhire": SignalhireClient(responder=sh_responder),
        "linkedin": None,
    }
    return clients, counters, reg


def _cfg():
    class C:
        class enrich:
            max_enrich = 100
        judge = JudgeConfig()
    return C()


def test_run_enrich_writes_people_and_phones(tmp_path):
    store = Store(tmp_path / "e.sqlite")
    store.init_db()
    _seed_company(store)
    clients, counters, reg = _clients(store)

    stats = run_enrich(_cfg(), store, clients=clients)
    assert stats["enriched"] == 1

    people = store.people_for("promatics.com")
    assert [p.name for p in people] == ["Arpit Jain", "Indu Jain"]
    primary = people[0]
    assert primary.is_primary is True
    assert primary.name_source == "registry"
    assert primary.phone == "+919876543210"
    assert primary.phone_source == "signalhire"
    # LinkedIn stays blank by default (Phase 4 confirms before any write)
    assert primary.linkedin_url is None
    # second founder = SPOC2, no phone (only one number returned)
    assert people[1].is_primary is False
    assert people[1].phone is None
    store.close()


def test_run_enrich_is_idempotent_no_recalls(tmp_path):
    store = Store(tmp_path / "e2.sqlite")
    store.init_db()
    _seed_company(store)
    clients, counters, reg = _clients(store)

    run_enrich(_cfg(), store, clients=clients)
    after_first = (reg.calls, counters["claude"], counters["sh"])
    assert reg.calls == 1 and counters["claude"] == 1 and counters["sh"] > 0

    # second run: everything served from cache → zero new external calls
    run_enrich(_cfg(), store, clients=clients)
    assert (reg.calls, counters["claude"], counters["sh"]) == after_first
    store.close()


def test_run_enrich_no_founder_flags_verify(tmp_path):
    store = Store(tmp_path / "e3.sqlite")
    store.init_db()
    store.upsert_company(
        Company(domain="ghost.com", company_name="Ghost Co", city="Pune",
                founded_year=2015, size_band="10-49", gate_pass=True)
    )
    clients = {
        "fetcher": None,
        "claude": ClaudeClient(responder=lambda s, u, m: "[]", store=store),
        "registry": FakeRegistry.__new__(FakeRegistry),  # returns text, claude returns []
        "company_site": None,
        "signalhire": None,
        "linkedin": None,
    }
    # make the registry return text so extract runs but yields nothing
    clients["registry"].calls = 0
    run_enrich(_cfg(), store, clients=clients)
    people = store.people_for("ghost.com")
    assert len(people) == 1
    assert people[0].name == "(verify)"
    assert "pull MCA" in (people[0].notes or "")
    store.close()
