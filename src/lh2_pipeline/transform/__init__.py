"""Phase 2 transform: canonicalize, dedupe, gate-filter (raw_listings -> companies)."""

from __future__ import annotations

import csv

from ..logging_setup import get_logger
from .canonicalize import canonical_domain, normalize_founded, normalize_size  # re-export
from .dedupe import dedupe
from .exclusions import load_exclusions
from .gates import apply_gates

log = get_logger("lh2.build")

__all__ = ["run_build", "canonical_domain", "normalize_founded", "normalize_size",
           "dedupe", "apply_gates", "load_known_names", "load_exclusions"]


def load_known_names(cfg) -> list[str]:  # noqa: ANN001
    """Already-known LH2 firm names from the configured CSV (the 'Company' column)."""
    rel = cfg.gates.blocklist_known_file
    if not rel:
        return []
    path = cfg.abspath(rel)
    if not path.exists():
        log.info("known_file_missing", path=str(path))
        return []
    names: list[str] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        # find the Company column (default index 1)
        col = 1
        if header:
            for i, h in enumerate(header):
                if h.strip().lower() == "company":
                    col = i
                    break
        for row in reader:
            if len(row) > col and row[col].strip():
                names.append(row[col].strip())
    log.info("known_names_loaded", count=len(names))
    return names


def run_build(cfg, store) -> dict:  # noqa: ANN001
    """Read raw_listings, dedupe to companies, apply gates, upsert. Returns counts."""
    raw = list(store.iter_raw_listings())
    result = dedupe(raw)

    # Persist the no-domain bucket for human review.
    for r in result.no_domain:
        store.add_no_domain(r.company_name, r.city, r.source, r.source_url)

    exclusions = load_exclusions(cfg)

    passing = 0
    excluded_known = 0
    for co in result.companies.values():
        apply_gates(co, cfg.gates, known_names=exclusions.names,
                    known_domains=exclusions.domains)
        if co.gate_pass:
            passing += 1
        elif co.gate_reason and "already-known" in co.gate_reason:
            excluded_known += 1
        store.upsert_company(co)

    counts = {
        "raw_listings": len(raw),
        "unique_companies": len(result.companies),
        "gate_pass": passing,
        "excluded_known": excluded_known,
        "no_domain": len(result.no_domain),
    }
    log.info("build_complete", **counts)
    return counts
