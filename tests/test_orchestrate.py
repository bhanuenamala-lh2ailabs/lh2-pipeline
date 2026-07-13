"""Phase 6 DoD: a second consecutive run makes ~zero external calls (all cache
hits) and re-produces the same export."""

from __future__ import annotations

from pathlib import Path

from lh2_pipeline.config import load_config
from lh2_pipeline.enrich import run_enrich
from lh2_pipeline.judge.claude_client import ClaudeClient
from lh2_pipeline.enrich.signalhire import SignalhireClient
from lh2_pipeline.export import run_export
from lh2_pipeline.models import Company, RawListing
from lh2_pipeline.store import Store


class _Reg:
    def __init__(self):
        self.calls = 0

    def director_text(self, name, city):
        self.calls += 1
        return "Directors: Asha Rao (Director)"


def _clients(store, counters):
    def claude_responder(system, user, model):
        counters["claude"] += 1
        return '[{"name":"Asha Rao","role":"Director"}]'

    def sh_responder(path, payload):
        counters["sh"] += 1
        if path.endswith("searchByQuery"):
            return {"profiles": [{"fullName": "Asha Rao", "uid": "X1",
                                  "experience": [{"company": payload.get("currentCompany", ""),
                                                  "title": "Director"}]}]}
        return [{"item": "X1", "status": "success",
                 "candidate": {"contacts": [{"type": "phone", "value": "9811122233"}]}}]

    return {
        "fetcher": None,
        "claude": ClaudeClient(responder=claude_responder, store=store),
        "registry": _Reg(),
        "company_site": None,
        "signalhire": SignalhireClient(responder=sh_responder),
        "linkedin": None,
    }


def test_second_run_zero_external_calls_and_identical_export(tmp_path, monkeypatch):
    # use a temp project so config paths resolve into tmp
    cfg = load_config(Path("config.yaml"))
    store = Store(tmp_path / "p.sqlite")
    store.init_db()

    # seed raw -> build to companies
    store.insert_raw_listing(RawListing(source="goodfirms", source_url="g1",
                                        company_name="Asha Tech", website_raw="ashatech.in",
                                        city="Pune", founded_year_raw="2016", size_raw="50-249"))
    from lh2_pipeline.transform import run_build
    run_build(cfg, store)

    counters = {"claude": 0, "sh": 0}
    clients = _clients(store, counters)

    # first enrich
    run_enrich(cfg, store, clients=clients)
    first = (clients["registry"].calls, counters["claude"], counters["sh"])
    assert clients["registry"].calls == 1 and counters["claude"] == 1 and counters["sh"] > 0

    # export 1
    out1 = tmp_path / "e1.csv"
    run_export(cfg, store, hyperlinked=True, out=out1)
    content1 = out1.read_text(encoding="utf-8")

    # second consecutive run — everything cached
    run_enrich(cfg, store, clients=clients)
    second = (clients["registry"].calls, counters["claude"], counters["sh"])
    assert second == first  # zero new external calls

    out2 = tmp_path / "e2.csv"
    run_export(cfg, store, hyperlinked=True, out=out2)
    content2 = out2.read_text(encoding="utf-8")

    assert content1 == content2  # identical export
    store.close()
