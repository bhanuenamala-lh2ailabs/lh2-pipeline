"""Dedupe raw_listings -> one Company per canonical registered domain.

Same firm appearing on 4 directories + 5 city pages collapses to one row,
unioning the sources list and keeping the most specific founded/size values.
Listings with no resolvable domain go to the `no_domain` bucket for human
review (we do NOT guess a domain).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..models import Company, RawListing
from .canonicalize import canonical_domain, normalize_founded, normalize_size


@dataclass
class DedupeResult:
    companies: dict[str, Company] = field(default_factory=dict)
    no_domain: list[RawListing] = field(default_factory=list)


def _best_name(names: list[str]) -> str:
    names = [n.strip() for n in names if n and n.strip()]
    if not names:
        return ""
    # Most frequent; tie-break by longest (more complete legal-ish name).
    counts = Counter(names)
    top = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))
    return top[0]


def dedupe(raw: Iterable[RawListing], reference_year: Optional[int] = None) -> DedupeResult:
    groups: dict[str, list[RawListing]] = {}
    res = DedupeResult()

    for r in raw:
        dom = canonical_domain(r.website_raw)
        if not dom:
            res.no_domain.append(r)
            continue
        groups.setdefault(dom, []).append(r)

    for dom, items in groups.items():
        name = _best_name([i.company_name for i in items])

        # website: first listing that yielded this domain
        website = next((i.website_raw for i in items if i.website_raw), None)

        # city: first non-empty
        city = next((i.city for i in items if i.city), None)

        # founded: prefer an exact parsed year; else first approximate.
        founded_year = None
        founded_source = None
        approx_note = None
        for i in items:
            fr = normalize_founded(i.founded_year_raw, reference_year)
            if fr.year is not None and not fr.approximate:
                founded_year, founded_source = fr.year, i.founded_year_raw
                approx_note = None
                break
            if fr.year is not None and founded_year is None:
                founded_year, founded_source = fr.year, i.founded_year_raw
                approx_note = fr.note

        # size: first listing that maps to a band; keep raw as provenance.
        size_band = None
        size_source = None
        for i in items:
            band = normalize_size(i.size_raw)
            if band:
                size_band, size_source = band, i.size_raw
                break

        # segment: first non-empty
        segment = next((i.segment_raw for i in items if i.segment_raw), None)

        # sources: union of distinct {source, url}
        seen = set()
        sources_json = []
        for i in items:
            key = (i.source, i.source_url)
            if key not in seen:
                seen.add(key)
                sources_json.append({"source": i.source, "url": i.source_url})

        co = Company(
            domain=dom,
            company_name=name,
            website=website,
            city=city,
            hq_country=None,           # set by the gate (India-delivery default)
            founded_year=founded_year,
            founded_source=founded_source,
            size_band=size_band,
            size_source=size_source,
            segment=segment,
            sources_json=sources_json,
        )
        if approx_note:
            co.gate_reason = approx_note  # carried forward; gate appends to it
        res.companies[dom] = co

    return res
