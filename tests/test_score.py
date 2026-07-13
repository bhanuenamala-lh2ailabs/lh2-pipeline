"""Phase 4 tests: confidence scoring, registry-overrides-aggregator, and the
namesake guard (wrong profile -> match 'no' -> LinkedIn stays blank)."""

from __future__ import annotations

from lh2_pipeline.config import EnrichConfig, JudgeConfig, Secrets
from lh2_pipeline.judge import run_score
from lh2_pipeline.judge.claude_client import ClaudeClient
from lh2_pipeline.judge.confidence import (
    reconcile_registry_vs_aggregator,
    score_person,
)
from lh2_pipeline.models import Company, Confidence, Person
from lh2_pipeline.store import Store


# --- confidence ------------------------------------------------------------ #
def test_score_green_when_two_independent_sources():
    p = Person(domain="x.com", name="Arpit Jain", name_source="registry",
               notes="sources: registry, company_site")
    assert score_person(p) == Confidence.green


def test_score_amber_single_source():
    p = Person(domain="x.com", name="Arpit Jain", name_source="registry",
               notes="sources: registry")
    assert score_person(p) == Confidence.amber


def test_score_amber_when_li_present_but_unconfirmed():
    p = Person(domain="x.com", name="Arpit Jain", notes="sources: registry, company_site",
               linkedin_url="https://linkedin.com/in/x", linkedin_confirmed=False)
    assert score_person(p) == Confidence.amber


def test_score_red_for_verify_or_aggregator_only():
    assert score_person(Person(domain="x.com", name="(verify)")) == Confidence.red
    p = Person(domain="x.com", name="Someone", notes="sources: directory")
    assert score_person(p) == Confidence.red


# --- registry overrides aggregator (Promatics case) ------------------------ #
def test_registry_overrides_aggregator():
    people = [
        Person(domain="promatics.com", name="Arpit Jain", notes="sources: registry"),
        Person(domain="promatics.com", name="Indu Jain", notes="sources: registry"),
        Person(domain="promatics.com", name="Rauf Saiyed", notes="sources: directory"),
    ]
    applied = reconcile_registry_vs_aggregator(people)
    assert len(applied) == 1
    rauf = [p for p in people if "dropped aggregator" in (p.notes or "")][0]
    assert rauf.name == "(verify)"
    assert rauf.confidence == Confidence.red


# --- namesake guard via run_score ------------------------------------------ #
def _cfg():
    class C:
        judge = JudgeConfig()
        enrich = EnrichConfig()
        secrets = Secrets()
    return C()


def _store_with_company_and_candidate(tmp_path, candidate):
    store = Store(tmp_path / "s.sqlite")
    store.init_db()
    store.upsert_company(Company(domain="acme.com", company_name="Acme Software",
                                 city="Pune", founded_year=2015, size_band="50-249",
                                 gate_pass=True))
    store.upsert_person(Person(domain="acme.com", name="Ravi Kumar",
                               name_source="registry", is_primary=True,
                               notes="sources: registry, company_site"))
    store.cache_set("linkedin:candidates:acme.com", [candidate])
    return store


def test_namesake_wrong_profile_leaves_linkedin_blank(tmp_path):
    # candidate has matching name but works at a DIFFERENT company
    candidate = {"name": "Ravi Kumar", "headline": "Engineer at Globex",
                 "experience_text": "Globex Corp 2018-now", "url": "https://linkedin.com/in/ravi-wrong"}
    store = _store_with_company_and_candidate(tmp_path, candidate)

    def responder(system, user, model):
        return '{"match": "no", "reason": "profile references Globex, not Acme"}'

    clients = {"claude": ClaudeClient(responder=responder, store=store)}
    stats = run_score(_cfg(), store, clients=clients)

    p = store.people_for("acme.com")[0]
    assert p.linkedin_url is None
    assert p.linkedin_confirmed is False
    assert stats["linkedin_rejected"] == 1
    assert "LI tentative" in (p.notes or "")
    store.close()


def test_namesake_correct_profile_confirms_linkedin(tmp_path):
    candidate = {"name": "Ravi Kumar", "headline": "Founder at Acme Software",
                 "experience_text": "Acme Software, Pune, Founder & CEO",
                 "url": "https://linkedin.com/in/ravi-right"}
    store = _store_with_company_and_candidate(tmp_path, candidate)

    def responder(system, user, model):
        return '{"match": "yes", "reason": "current role is Founder at Acme Software"}'

    clients = {"claude": ClaudeClient(responder=responder, store=store)}
    stats = run_score(_cfg(), store, clients=clients)

    p = store.people_for("acme.com")[0]
    assert p.linkedin_url == "https://linkedin.com/in/ravi-right"
    assert p.linkedin_confirmed is True
    assert p.confidence == Confidence.green   # 2 sources + confirmed LI
    assert stats["linkedin_confirmed"] == 1
    store.close()
