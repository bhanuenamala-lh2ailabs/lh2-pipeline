"""Gate-filter qualifying firms (config-driven thresholds).

A failing firm is NOT deleted — it stays in `companies` with gate_pass=False and
a gate_reason, as audit trail + denominator. Fail-closed on unknowns (a smaller
correct dataset beats a larger guessed one).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

from ..models import Company


@dataclass
class GateOutcome:
    passed: bool
    reasons: list[str]
    notes: list[str]


# Generic corporate tokens stripped before known-firm matching, so exclusion
# keys on the distinctive core (e.g. "Velotio") not shared suffixes
# ("Technologies", "Solutions") that would over-match net-new firms.
_GENERIC_TOKENS = {
    "technologies", "technology", "technolabs", "tech", "solutions", "solution",
    "software", "softwares", "labs", "lab", "systems", "system", "services",
    "service", "consulting", "consultancy", "infotech", "infosystems", "digital",
    "studio", "studios", "global", "worldwide", "group", "ventures",
    "pvt", "private", "ltd", "limited", "llp", "inc", "incorporated", "co",
    "company", "corp", "corporation", "india", "indian",
}


def _normalize_company(name: str) -> frozenset[str]:
    """Lowercase, drop punctuation/parentheses, remove generic corporate tokens,
    return the distinctive core token set."""
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    tokens = {t for t in s.split() if t and t not in _GENERIC_TOKENS}
    return frozenset(tokens)


def matches_known_firm(name: str, known_names: list[str], threshold: int = 92) -> Optional[str]:
    """Return the known firm that ``name`` matches (core-name equality or strong
    fuzzy on the distinctive core), else None."""
    core = _normalize_company(name)
    if not core:
        return None
    core_str = " ".join(sorted(core))
    # Fuzzy matching needs a substantive core; a tiny core like {"it"} would
    # over-match (e.g. "IT Services India" vs "Golden Eagle IT Technologies").
    fuzzy_ok = len(core_str) >= 5
    for k in known_names:
        kcore = _normalize_company(k)
        if not kcore:
            continue
        if core == kcore:
            return k
        if fuzzy_ok and len(" ".join(kcore)) >= 5:
            if fuzz.token_set_ratio(core_str, " ".join(sorted(kcore))) >= threshold:
                return k
    return None


def _name_matches_blocklist(name: str, blocklist: list[str], threshold: int = 90) -> Optional[str]:
    n = name.strip().lower()
    if not n:
        return None
    for b in blocklist:
        bl = b.strip().lower()
        if not bl:
            continue
        # word-boundary substring OR strong fuzzy match
        if re.search(rf"\b{re.escape(bl)}\b", n) or fuzz.token_set_ratio(n, bl) >= threshold:
            return b
    return None


def apply_gates(
    co: Company,
    gates,                                  # noqa: ANN001
    reference_year: Optional[int] = None,
    known_names: Optional[list[str]] = None,
    known_domains: Optional[set[str]] = None,
) -> GateOutcome:
    """Evaluate a company against the configured gates. Mutates ``co`` to set
    hq_country default and returns the outcome (also reflected on co).

    ``known_names`` / ``known_domains`` (already-known or previously-mined firms)
    keep output net-new: pass them in from run_build (loaded by
    exclusions.load_exclusions from the master list + prior deliverables).
    """
    reasons: list[str] = []
    notes: list[str] = []

    # Carry any approximate-founded note from dedupe into notes.
    if co.gate_reason:
        notes.append(co.gate_reason)

    # 1a. Already-known / previously-mined firm (net-new output) — domain match.
    known = {d.strip().lower() for d in (gates.blocklist_known_domains or []) if d.strip()}
    if known_domains:
        known |= {d.strip().lower() for d in known_domains if d and d.strip()}
    if co.domain.lower() in known:
        reasons.append("already-known LH2 firm (domain)")

    # 1b. Already-known LH2 firm — core-name match (config names + file).
    name_blocklist = list(gates.blocklist_known_names or []) + list(known_names or [])
    nhit = matches_known_firm(co.company_name, name_blocklist)
    if nhit:
        reasons.append(f"already-known LH2 firm ({nhit})")

    # 2. Large outsourcer blocklist (name match).
    hit = _name_matches_blocklist(co.company_name, gates.blocklist_outsourcers or [])
    if hit:
        reasons.append(f"blocklisted outsourcer ({hit})")

    # 3. HQ / India delivery. Sources are India city pages → default India-delivery.
    if not co.hq_country:
        co.hq_country = gates.hq_country  # "India"
    elif co.hq_country.strip().lower() != gates.hq_country.strip().lower():
        notes.append(f"foreign-incorporated ({co.hq_country}); India-delivery assumed")

    # 4. Founded year <= max.
    if co.founded_year is None:
        reasons.append("founded year unknown")
    elif co.founded_year > gates.founded_max_year:
        reasons.append(f"founded {co.founded_year} > {gates.founded_max_year}")

    # 5. Size band in include set.
    if co.size_band is None:
        reasons.append("size band unknown")
    elif co.size_band in (gates.size_bands_exclude or []):
        reasons.append(f"size {co.size_band} excluded")
    elif co.size_band not in (gates.size_bands_include or []):
        reasons.append(f"size {co.size_band} not in target bands")
    else:
        # near-ceiling flag: only when a *precise* headcount (single number) is
        # close to 250 — not when size_source is just the band range "50-249".
        if co.size_band == "50-249" and co.size_source:
            nums = [int(x) for x in re.findall(r"\d+", co.size_source.replace(",", ""))]
            if len(nums) == 1 and 200 <= nums[0] <= 249:
                notes.append("near-250 headcount ceiling")

    passed = len(reasons) == 0
    co.gate_pass = passed
    co.gate_reason = "; ".join(reasons + notes) if (reasons or notes) else None
    return GateOutcome(passed=passed, reasons=reasons, notes=notes)
