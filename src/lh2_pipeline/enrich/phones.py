"""E.164 phone normalization (default region India / +91).

Kept dependency-free (no phonenumbers): the inputs come from Signalhire and are
mostly Indian mobiles. We normalize confidently or return None — never fabricate.
"""

from __future__ import annotations

import re
from typing import Optional

_CC = {"IN": "91"}


def normalize_e164(raw: Optional[str], region: str = "IN") -> Optional[str]:
    if not raw:
        return None
    s = raw.strip()
    had_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None

    cc = _CC.get(region.upper(), "91")

    if had_plus:
        # already international
        return "+" + digits

    # 00 international prefix
    if digits.startswith("00"):
        return "+" + digits[2:]

    # leading country code without '+'
    if digits.startswith(cc) and len(digits) > 10:
        return "+" + digits

    # national trunk '0' + 10-digit mobile
    if digits.startswith("0") and len(digits) == 11:
        return "+" + cc + digits[1:]

    # bare 10-digit national number
    if len(digits) == 10:
        return "+" + cc + digits

    # Can't normalize confidently → leave for human (don't guess).
    return None
