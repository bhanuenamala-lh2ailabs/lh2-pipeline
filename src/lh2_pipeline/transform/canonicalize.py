"""Field normalization: canonical domain (the dedupe key), founded year, size band.

Per the accuracy rules: never fabricate. Where a value can't be normalized
confidently, we keep an approximate flag / "(verify)" tag rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import tldextract

# tldextract with no live suffix-list fetch (deterministic, offline-friendly).
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


# --------------------------------------------------------------------------- #
# Domain
# --------------------------------------------------------------------------- #
def canonical_domain(website: Optional[str]) -> Optional[str]:
    """Return the canonical registered domain (lowercase, no www/path/query).

    e.g. "https://www.CMARIX.com/services?x=1" -> "cmarix.com".
    Returns None when no registrable domain can be extracted.
    """
    if not website:
        return None
    raw = website.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    ext = _EXTRACT(raw)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


# --------------------------------------------------------------------------- #
# Founded year
# --------------------------------------------------------------------------- #
@dataclass
class FoundedResult:
    year: Optional[int]
    source_raw: Optional[str]
    approximate: bool = False
    note: Optional[str] = None


_DECADE_WORDS = {
    "one decade": 10, "a decade": 10, "two decades": 20, "three decades": 30,
    "four decades": 40, "two decade": 20,
}


def _current_year(reference_year: Optional[int]) -> int:
    return reference_year or datetime.now(timezone.utc).year


def normalize_founded(raw: Optional[str], reference_year: Optional[int] = None) -> FoundedResult:
    """Normalize a founded-year string to an int, tagging approximations.

    Handles: "2015", "since 2015", "Founded 2015", "Est. 2015",
             "11+ years" -> reference_year - 11 (approx),
             "two decades" -> ~reference_year-20 with "(verify)" note.
    """
    if not raw:
        return FoundedResult(None, raw)
    s = raw.strip().lower()
    cur = _current_year(reference_year)

    # Explicit 4-digit year (most reliable).
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    if m:
        return FoundedResult(int(m.group(1)), raw)

    # "N+ years" / "N years" of experience -> derive approximate founding year.
    m = re.search(r"(\d{1,2})\s*\+?\s*years?", s)
    if m:
        n = int(m.group(1))
        return FoundedResult(cur - n, raw, approximate=True,
                             note=f"approx from '{raw.strip()}'")

    # "N decades" worded.
    for phrase, yrs in _DECADE_WORDS.items():
        if phrase in s:
            return FoundedResult(cur - yrs, raw, approximate=True,
                                 note=f"~{cur - yrs} (verify) from '{raw.strip()}'")

    return FoundedResult(None, raw, note=f"unparsed founded '{raw.strip()}'")


# --------------------------------------------------------------------------- #
# Size band
# --------------------------------------------------------------------------- #
# Canonical bands. Include set is config-driven in the gate; here we only map.
BAND_UNDER_10 = "<10"
BAND_10_49 = "10-49"
BAND_50_249 = "50-249"
BAND_250_PLUS = "250+"


def normalize_size(raw: Optional[str]) -> Optional[str]:
    """Map a raw team-size string to a canonical band, else None.

    Examples: "50 - 249" -> "50-249"; "10 to 49 employees" -> "10-49";
              "1,000+" -> "250+"; "Freelancer (1)" -> "<10".
    The decision uses the *lower bound* of any range, mapped to the band it
    falls in. A single number maps by the band it falls in.
    """
    if not raw:
        return None
    s = raw.replace(",", "").lower()

    nums = [int(x) for x in re.findall(r"\d+", s)]
    if not nums:
        return None

    # Range -> use lower bound; single number -> itself.
    low = min(nums)

    if low < 10:
        return BAND_UNDER_10
    if low < 50:
        return BAND_10_49
    if low < 250:
        return BAND_50_249
    return BAND_250_PLUS
