"""Confidence scoring + registry-overrides-aggregator deterministic rule.

green — name agrees across >=2 independent sources (registry ≈ company_site)
        AND, if a LinkedIn URL is present, it passed the namesake match.
amber — single source, mild disagreement, or LinkedIn present but match uncertain.
red   — only a weak/aggregator source, or an unresolved name conflict.

Independent sources: registry, company_site. "directory" is an aggregator (weak).
"""

from __future__ import annotations

import re
from typing import Iterable

from rapidfuzz import fuzz

from ..models import Confidence, Person

INDEPENDENT = {"registry", "company_site"}
AGGREGATOR = {"directory"}


def parse_sources(person: Person) -> set[str]:
    """Recover the founder-name sources recorded by enrich (notes: 'sources: a, b'),
    falling back to the single name_source."""
    srcs: set[str] = set()
    if person.notes:
        m = re.search(r"sources:\s*([a-z_,\s]+)", person.notes, flags=re.IGNORECASE)
        if m:
            srcs = {s.strip().lower() for s in m.group(1).split(",") if s.strip()}
    if not srcs and person.name_source:
        ns = person.name_source.value if hasattr(person.name_source, "value") else person.name_source
        srcs = {str(ns).lower()}
    return srcs


def score_person(person: Person) -> Confidence:
    if not person.name or person.name.strip() in ("", "(verify)"):
        return Confidence.red

    srcs = parse_sources(person)
    independent_hits = len(srcs & INDEPENDENT)
    only_aggregator = bool(srcs) and srcs.issubset(AGGREGATOR)

    has_li = bool(person.linkedin_url)
    li_ok = person.linkedin_confirmed

    if only_aggregator:
        return Confidence.red

    if independent_hits >= 2:
        # corroborated name; LinkedIn (if any) must be confirmed for green
        if has_li and not li_ok:
            return Confidence.amber
        return Confidence.green

    # single independent source
    if has_li and not li_ok:
        return Confidence.amber
    return Confidence.amber


def reconcile_registry_vs_aggregator(people: Iterable[Person], fuzzy_threshold: int = 88) -> list[str]:
    """Deterministic rule: registry beats aggregator. If an aggregator-sourced
    person's name conflicts with a registry-sourced name (same person slot), drop
    the aggregator name from output and note the override. Returns notes applied.

    Encodes the Promatics case: registry=Arpit/Indu Jain beats aggregator 'Rauf Saiyed'.
    """
    notes: list[str] = []
    registry_names = [
        p.name for p in people
        if "registry" in parse_sources(p) and p.name and p.name != "(verify)"
    ]
    if not registry_names:
        return notes

    for p in people:
        srcs = parse_sources(p)
        if srcs and srcs.issubset(AGGREGATOR):
            # is this aggregator name absent from registry? then it's a conflict
            agrees = any(
                fuzz.token_set_ratio(p.name.lower(), rn.lower()) >= fuzzy_threshold
                for rn in registry_names
            )
            if not agrees:
                note = f"registry-vs-aggregator override: dropped aggregator name '{p.name}'"
                p.name = "(verify)"
                p.confidence = Confidence.red
                p.notes = (p.notes + "; " if p.notes else "") + note
                notes.append(note)
    return notes
