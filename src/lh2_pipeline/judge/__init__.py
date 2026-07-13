"""Phase 4 judgment: namesake guard (before writing any LinkedIn URL) +
confidence scoring + registry-overrides-aggregator rule."""

from __future__ import annotations

from typing import Optional

from rapidfuzz import fuzz

from ..logging_setup import get_logger
from .claude_client import ClaudeClient
from .confidence import reconcile_registry_vs_aggregator, score_person
from .match import match_profile

log = get_logger("lh2.score")

__all__ = ["run_score", "score_person", "reconcile_registry_vs_aggregator",
           "match_profile", "ClaudeClient"]


def _best_candidate(name: str, candidates: list[dict], threshold: int) -> Optional[dict]:
    best, best_score = None, 0
    for c in candidates:
        sc = fuzz.token_set_ratio(name.lower(), (c.get("name") or "").lower())
        if sc > best_score:
            best, best_score = c, sc
    return best if best_score >= threshold else None


def run_score(cfg, store, clients=None) -> dict:  # noqa: ANN001
    threshold = cfg.judge.fuzzy_threshold
    provider = cfg.enrich.linkedin_optional.provider

    claude = (clients or {}).get("claude") if clients else None
    if claude is None:
        claude = ClaudeClient(
            api_key=cfg.secrets.anthropic_api_key,
            model_default=cfg.judge.model_match,
            store=store,
            max_tokens=cfg.judge.max_tokens,
        )

    stats = {"people": 0, "green": 0, "amber": 0, "red": 0,
             "linkedin_confirmed": 0, "linkedin_rejected": 0, "overrides": 0}

    for co in store.iter_companies(gate_pass=True):
        people = store.people_for(co.domain)
        if not people:
            continue

        # 1. deterministic registry-overrides-aggregator
        applied = reconcile_registry_vs_aggregator(people, threshold)
        stats["overrides"] += len(applied)

        # 2. namesake guard for any cached LinkedIn candidates (Proxycurl/Coresignal)
        candidates = store.cache_get(f"linkedin:candidates:{co.domain}") or []
        for p in people:
            if candidates and not p.linkedin_confirmed and p.name and p.name != "(verify)":
                cand = _best_candidate(p.name, candidates, threshold)
                if cand and cand.get("url"):
                    profile_text = f"{cand.get('headline','')} {cand.get('experience_text','')}".strip()
                    verdict = match_profile(claude, p.name, co.company_name, co.city or "", profile_text)
                    if verdict["match"] == "yes":
                        p.linkedin_url = cand["url"]
                        p.linkedin_source = provider
                        p.linkedin_confirmed = True
                        stats["linkedin_confirmed"] += 1
                    else:
                        p.notes = (p.notes + "; " if p.notes else "") + \
                                  f"LI tentative ({verdict['match']}): {verdict['reason']}"
                        stats["linkedin_rejected"] += 1

            # 3. confidence
            if p.confidence is None:
                p.confidence = score_person(p)
            stats[p.confidence.value] += 1
            stats["people"] += 1
            store.upsert_person(p)

    log.info("score_complete", **stats)
    return stats
