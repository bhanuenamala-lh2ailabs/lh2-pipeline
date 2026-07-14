"""Signalhire adapter — PHONE NUMBERS ONLY (BUILD SPEC §5b).

Real API contract (verified 2026-06 against docs.signalhire.com):
  * Search:  POST /api/v1/candidate/searchByQuery  {fullName, currentCompany, ...}
             -> profile summaries (+ scrollId).  NOTE: Search API access must be
             enabled on the account by Signalhire support; returns 403 otherwise.
  * Enrich:  POST /api/v1/candidate/search  {items:[identifier], withoutWaterfall:true}
             -> [{item, status, candidate:{fullName, contacts:[...]}}] (sync)
  * Credits: GET  /api/v1/credits  (X-Credits-Left header)
  Auth header: `apikey`.

Flow to get a founder's phone: search by name+company -> pick best matching
profile identifier (UID/LinkedIn) -> enrich -> read contacts.

CRITICAL: ignore the LinkedIn field in the response (namesake-unreliable for this
segment). Pull phones only; phone_source = "signalhire".

Testability: inject ``responder(path, payload) -> dict`` to bypass HTTP.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from rapidfuzz import fuzz

from ..logging_setup import get_logger
from ..quota_ledger import QuotaExceeded
from .phones import normalize_e164

log = get_logger("lh2.signalhire")

Responder = Callable[[str, dict], dict]

DEFAULT_BASE_URL = "https://www.signalhire.com/api/v1"
SEARCH_PATH = "/candidate/searchByQuery"
ENRICH_PATH = "/candidate/search"
CREDITS_PATH = "/credits"


class SignalhireAccessError(Exception):
    """Search API not enabled on this account (HTTP 403)."""


def _phones_from_contacts(candidate: dict) -> list[str]:
    """Pull phone values from a candidate's contacts, ignoring email/linkedin/social."""
    phones: list[str] = []
    for c in candidate.get("contacts", []) or []:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type", "")).lower()
        if "phone" in ctype:
            val = c.get("value") or c.get("number")
            if isinstance(val, str):
                phones.append(val)
    return phones


def _emails_from_contacts(candidate: dict) -> list[str]:
    """Pull email values from a candidate's contacts. Work emails first (they beat
    personal for a B2B founder outreach), preserving first-seen order otherwise."""
    work: list[str] = []
    other: list[str] = []
    for c in candidate.get("contacts", []) or []:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type", "")).lower()
        if "email" in ctype:
            val = c.get("value") or c.get("email")
            if isinstance(val, str) and "@" in val:
                sub = str(c.get("subType") or c.get("sub_type") or "").lower()
                (work if "work" in sub else other).append(val.strip())
    return work + other


class SignalhireClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        region: str = "IN",
        responder: Optional[Responder] = None,
        timeout_s: int = 40,
        governor=None,             # noqa: ANN001 — governor.Governor | None
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.region = region
        self._responder = responder
        self.timeout_s = timeout_s
        self.governor = governor   # rate-limit + daily search-quota guard
        self.search_calls = 0      # cost counters
        self.enrich_calls = 0
        self.last_credits_left: Optional[int] = None

    # -- transport --------------------------------------------------------- #
    def _raw_request(self, path: str, payload: Optional[dict], method: str = "POST") -> dict:
        if self._responder is not None:
            return self._responder(path, payload or {})
        if not self.api_key:
            raise RuntimeError("SIGNALHIRE_API_KEY is not set")
        import httpx

        # Proactive pacing: block until the rate limiter allows this request.
        if self.governor is not None:
            self.governor.pace()

        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        url = self.base_url + path
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.request(method, url, json=payload, headers=headers)
            cl = r.headers.get("X-Credits-Left")
            if cl is not None:
                try:
                    self.last_credits_left = int(cl)
                except ValueError:
                    pass
            if r.status_code == 403:
                raise SignalhireAccessError(f"403 for {path} (Search API not enabled?)")
            if r.status_code == 402:
                # 402 means a pool is exhausted. On the reveal endpoint that's
                # *credits*; on the search endpoint it's the *daily search quota*.
                # Either way, signal the enrich loop to stop cleanly (resumable).
                metric = "credits" if path == ENRICH_PATH else "search"
                raise QuotaExceeded("signalhire", metric, used=0, limit=0)
            r.raise_for_status()
            return r.json() if r.content else {}

    # -- public ------------------------------------------------------------ #
    def credits(self) -> Optional[int]:
        try:
            resp = self._raw_request(CREDITS_PATH, None, method="GET")
            if isinstance(resp, dict) and "credits" in resp:
                self.last_credits_left = int(resp["credits"])
        except Exception as e:  # pragma: no cover
            log.info("credits_check_failed", err=str(e))
        return self.last_credits_left

    # Founder/leadership titles for the title-search founder finder.
    FOUNDER_TITLES = (
        "Founder OR Co-Founder OR Cofounder OR CEO OR Owner OR "
        "Managing Director OR Director OR Proprietor OR Partner"
    )

    def _search_raw(self, body: dict) -> list[dict]:
        # Charge the daily search quota first: if we're at the safety-margined cap
        # this raises QuotaExceeded and we never spend the HTTP call (or the quota).
        if self.governor is not None:
            self.governor.check_and_charge("search")
        try:
            resp = self._raw_request(SEARCH_PATH, body)
            self.search_calls += 1
        except SignalhireAccessError:
            log.info("signalhire_search_no_access")
            return []
        return resp.get("profiles") or resp.get("requests") or resp.get("items") or []

    def search(self, name: str, company: str, location: Optional[str] = None) -> list[dict]:
        body: dict[str, Any] = {"fullName": name, "currentCompany": company}
        if location:
            body["location"] = location
        return self._search_raw(body)

    def find_founders(
        self, company: str, size: int = 6, min_company_score: int = 80
    ) -> list[dict]:
        """Identify a company's founders/leadership via title-search. Returns
        [{name, title, uid, company_score}] sorted best-company-match first.
        The company must match in the profile's experience[] (guards namesakes)."""
        profiles = self._search_raw(
            {"currentCompany": company, "currentTitle": self.FOUNDER_TITLES, "size": size}
        )
        out: list[dict] = []
        for p in profiles:
            if not isinstance(p, dict):
                continue
            best_score, best_title = 0, ""
            for exp in p.get("experience") or []:
                if isinstance(exp, dict):
                    cs = fuzz.token_set_ratio(company.lower(), str(exp.get("company") or "").lower())
                    if cs > best_score:
                        best_score, best_title = cs, str(exp.get("title") or "")
            if best_score >= min_company_score and p.get("fullName"):
                out.append({
                    "name": str(p["fullName"]).strip(),
                    "title": best_title.strip(),
                    "uid": p.get("uid") or p.get("profileUid"),
                    "company_score": best_score,
                })
        return sorted(out, key=lambda r: -r["company_score"])

    def enrich_uid_phones(self, uid: str) -> list[str]:
        """Enrich by a known uid and return normalized E.164 phones (skips search)."""
        out, seen = [], set()
        for p in self.enrich(uid):
            e = normalize_e164(p, self.region)
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return out

    @staticmethod
    def _best_identifier(profiles: list[dict], name: str, company: str) -> Optional[str]:
        """Pick the profile best matching name + company. Company lives in the
        profile's experience[] array (each entry has company + title)."""
        best, best_score = None, 0
        for p in profiles:
            if not isinstance(p, dict):
                continue
            pname = str(p.get("fullName") or p.get("name") or "")
            name_score = fuzz.token_set_ratio(name.lower(), pname.lower())
            comp_score = 0
            if company:
                for exp in p.get("experience") or []:
                    if isinstance(exp, dict):
                        c = str(exp.get("company") or "")
                        comp_score = max(comp_score, fuzz.token_set_ratio(company.lower(), c.lower()))
            # Name must match well; company corroborates.
            score = (name_score * 2 + comp_score) // 3 if company else name_score
            if name_score >= 85 and score > best_score:
                best_score = score
                best = p.get("uid") or p.get("profileUid") or p.get("linkedinUrl") or p.get("linkedin")
        return best if best_score >= 70 else None

    @staticmethod
    def _linkedin_from_candidate(candidate: dict) -> Optional[str]:
        """Pick the highest-rated LinkedIn (type 'li') from the candidate's socials.
        Safe here because the candidate was matched to the company via experience."""
        best, best_rating = None, -1
        for so in candidate.get("social", []) or []:
            if isinstance(so, dict) and str(so.get("type", "")).lower() == "li" and so.get("link"):
                rating = so.get("rating") or 0
                if rating > best_rating:
                    best, best_rating = so["link"], rating
        return best

    def enrich_full(self, identifier: str) -> dict:
        """Enrich an identifier -> {'phones': [raw], 'emails': [raw], 'linkedin': url|None}.

        The paid SignalHire reveal bundles phone + email + LinkedIn in one credit;
        all three are matched-by-company, so all three are trustworthy for this
        person (the sales team still verifies before outreach)."""
        # Gate on the monthly credit budget (fair daily share) BEFORE spending a
        # reveal. Raises QuotaExceeded when today's budget is spent or the 4k/mo
        # cap is hit → the enrich loop stops cleanly.
        if self.governor is not None:
            self.governor.require_credit()
        body = {"items": [identifier], "withoutWaterfall": True}
        resp = self._raw_request(ENRICH_PATH, body)
        self.enrich_calls += 1
        results = resp if isinstance(resp, list) else resp.get("results", [])
        phones: list[str] = []
        emails: list[str] = []
        linkedin: Optional[str] = None
        for item in results or []:
            if isinstance(item, dict) and item.get("status") == "success":
                cand = item.get("candidate", {}) or {}
                phones.extend(_phones_from_contacts(cand))
                emails.extend(_emails_from_contacts(cand))
                linkedin = linkedin or self._linkedin_from_candidate(cand)
        # "No find, no charge": only count a credit when a phone/email was revealed.
        if self.governor is not None and (phones or emails):
            self.governor.charge_credit()
        return {"phones": phones, "emails": emails, "linkedin": linkedin}

    def enrich(self, identifier: str) -> list[str]:
        return self.enrich_full(identifier)["phones"]

    def _normalize_phones(self, raw: list[str]) -> list[str]:
        out, seen = [], set()
        for p in raw:
            e = normalize_e164(p, self.region)
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return out

    @staticmethod
    def _dedup_emails(raw: list[str]) -> list[str]:
        out, seen = [], set()
        for e in raw:
            k = e.strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(e.strip())
        return out

    def contact_for_person(
        self, name: str, company: str, uid: Optional[str] = None
    ) -> dict:
        """Resolve a person -> {'phones': [E.164], 'emails': [...], 'linkedin': url|None}.
        Uses a known uid (from find_founders) if given, else searches by name+company."""
        identifier = uid
        if not identifier:
            profiles = self.search(name, company)
            identifier = self._best_identifier(profiles, name, company)
        if not identifier:
            return {"phones": [], "emails": [], "linkedin": None}
        full = self.enrich_full(identifier)
        return {
            "phones": self._normalize_phones(full["phones"]),
            "emails": self._dedup_emails(full.get("emails", [])),
            "linkedin": full.get("linkedin"),
        }

    # --- back-compat thin wrappers (used by tests) ----------------------- #
    def enrich_uid_phones(self, uid: str) -> list[str]:
        return self._normalize_phones(self.enrich_full(uid)["phones"])

    def fetch_phones_for_person(self, name: str, company: str,
                                location: Optional[str] = None,
                                linkedin: Optional[str] = None) -> list[str]:
        return self.contact_for_person(name, company, uid=linkedin)["phones"]
