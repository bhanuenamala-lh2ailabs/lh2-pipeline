"""Phase 3 enrichment orchestration: founders (registry + site) + contacts (Signalhire).

Only gate_pass companies. Everything cached by domain → a re-run with no
--refresh makes zero external calls. ``max_enrich`` caps billable work.

Clients are injectable (``clients=`` dict) for offline tests; production builds
real adapters from config + secrets.
"""

from __future__ import annotations

from typing import Optional

from rapidfuzz import fuzz

from ..logging_setup import get_logger
from ..models import Person
from ..governor import build_governor
from ..quota_ledger import QuotaExceeded
from ..judge.claude_client import ClaudeClient
from ..judge.extract import extract_directors
from .company_site import CompanySiteClient
from .linkedin_optional import LinkedinClient
from .registry_founders import RegistryClient
from .signalhire import SignalhireClient

log = get_logger("lh2.enrich")


# --------------------------------------------------------------------------- #
# Founder merge
# --------------------------------------------------------------------------- #
def _merge_people(registry_people, site_people, fuzzy_threshold: int):
    """Combine registry (authoritative) + company-site founders. Registry name
    wins on a fuzzy match; site contributes role if registry lacked one."""
    merged: list[dict] = []

    for rp in registry_people:
        merged.append({"name": rp["name"], "role": rp.get("role") or None,
                       "name_source": "registry", "sources": ["registry"]})

    for sp in site_people:
        match = None
        for m in merged:
            if fuzz.token_set_ratio(sp["name"].lower(), m["name"].lower()) >= fuzzy_threshold:
                match = m
                break
        if match:
            if not match["role"] and sp.get("role"):
                match["role"] = sp["role"]
            if "company_site" not in match["sources"]:
                match["sources"].append("company_site")  # corroboration
        else:
            merged.append({"name": sp["name"], "role": sp.get("role") or None,
                           "name_source": "company_site", "sources": ["company_site"]})
    return merged


def _cached_text(store, key: str, producer, refresh: bool) -> Optional[str]:  # noqa: ANN001
    if not refresh:
        cached = store.cache_get(key)
        if cached is not None:
            return cached or None
    text = producer()
    store.cache_set(key, text or "")
    return text or None


def _person_contact(store, sh, domain, name, company, refresh, uid=None):  # noqa: ANN001
    """Cached per-founder contact lookup (Signalhire) -> {'phones': [...], 'linkedin': url}.
    If a uid is known (from the founder title-search) we enrich it directly and
    skip the name search. Never passes the company HQ city as the person's
    location — Signalhire filters on the person's own location, which differs."""
    if sh is None or not name or name == "(verify)":
        return {"phones": [], "emails": [], "linkedin": None}
    key = f"signalhire:{domain}:{name.strip().lower()}"
    if not refresh:
        cached = store.cache_get(key)
        if cached is not None:
            # tolerate the old cache shape (bare phone list)
            if isinstance(cached, list):
                return {"phones": cached, "emails": [], "linkedin": None}
            cached.setdefault("emails", [])   # tolerate pre-email cached dicts
            return cached
    contact = sh.contact_for_person(name, company, uid=uid)
    store.cache_set(key, contact)
    return contact


def _merge_signalhire_founders(merged, sh_founders, fuzzy_threshold):
    """Fold Signalhire title-search founders into the merged list. Carries the
    uid (for direct phone enrichment) and tags the 'signalhire' source."""
    for f in sh_founders:
        match = None
        for m in merged:
            if fuzz.token_set_ratio(f["name"].lower(), m["name"].lower()) >= fuzzy_threshold:
                match = m
                break
        if match:
            if "signalhire" not in match["sources"]:
                match["sources"].append("signalhire")
            if not match.get("role") and f.get("title"):
                match["role"] = f["title"]
            if not match.get("uid"):
                match["uid"] = f.get("uid")
        else:
            merged.append({"name": f["name"], "role": f.get("title") or None,
                           "name_source": "signalhire", "sources": ["signalhire"],
                           "uid": f.get("uid")})
    return merged


# --------------------------------------------------------------------------- #
# Real client construction
# --------------------------------------------------------------------------- #
def _build_clients(cfg, store):  # noqa: ANN001
    from ..crawl.base import PlaywrightFetcher

    # company sites: domcontentloaded is far faster/safer than networkidle.
    fetcher = (PlaywrightFetcher(wait_until="domcontentloaded")
               if (cfg.enrich.registry.enabled or cfg.enrich.company_site.enabled) else None)
    claude = ClaudeClient(
        api_key=cfg.secrets.anthropic_api_key,
        model_default=cfg.judge.model_extract,
        store=store,
        max_tokens=cfg.judge.max_tokens,
    )
    return {
        "fetcher": fetcher,
        "claude": claude,
        "registry": RegistryClient(fetcher=fetcher) if cfg.enrich.registry.enabled else None,
        "company_site": CompanySiteClient(fetcher=fetcher) if cfg.enrich.company_site.enabled else None,
        "signalhire": SignalhireClient(
            api_key=cfg.secrets.signalhire_api_key,
            region=cfg.enrich.signalhire.e164_default_region,
            governor=build_governor(cfg, store, "signalhire"),
        ) if cfg.enrich.signalhire.enabled else None,
        "linkedin": LinkedinClient(
            provider=cfg.enrich.linkedin_optional.provider,
            api_key=(cfg.secrets.proxycurl_api_key or cfg.secrets.coresignal_api_key),
        ) if cfg.enrich.linkedin_optional.enabled else None,
    }


# --------------------------------------------------------------------------- #
# Per-firm enrichment (raises QuotaExceeded up to the loop on provider exhaustion)
# --------------------------------------------------------------------------- #
def _enrich_one(co, store, clients, threshold, stats, refresh) -> None:  # noqa: ANN001
    claude = clients.get("claude")
    registry = clients.get("registry")
    site = clients.get("company_site")
    sh = clients.get("signalhire")
    li = clients.get("linkedin")

    # --- founders (registry + site -> Claude extract) --------------------- #
    registry_people: list[dict] = []
    site_people: list[dict] = []

    if registry is not None and claude is not None:
        rtext = _cached_text(
            store, f"registry:text:{co.domain}",
            lambda: registry.director_text(co.company_name, co.city), refresh,
        )
        if rtext:
            registry_people = extract_directors(claude, co.company_name, co.city or "", rtext)

    if site is not None and claude is not None:
        stext = _cached_text(
            store, f"site:text:{co.domain}",
            lambda: site.leadership_text(co.website), refresh,
        )
        if stext:
            site_people = extract_directors(claude, co.company_name, co.city or "", stext)

    merged = _merge_people(registry_people, site_people, threshold)

    # --- Signalhire founder title-search (fills + corroborates names) ----- #
    if sh is not None:
        key = f"signalhire:founders:{co.domain}"
        sh_founders = None if refresh else store.cache_get(key)
        if sh_founders is None:
            sh_founders = sh.find_founders(co.company_name)
            store.cache_set(key, sh_founders)
        merged = _merge_signalhire_founders(merged, sh_founders, threshold)

    # --- optional LinkedIn candidates (cached for Phase 4) ---------------- #
    if li is not None:
        store.cache_set(f"linkedin:candidates:{co.domain}", li.candidates(domain=co.domain))

    # --- write people (phone/email fetched per founder name) -------------- #
    # Clean slate so re-runs don't leave stale (verify)/old founder rows.
    store.delete_people(co.domain)
    if not merged:
        # No founder found anywhere → explicit (verify), flag for MCA pull.
        store.upsert_person(Person(domain=co.domain, name="(verify)",
                                   is_primary=True, notes="no founder found - pull MCA"))
        return

    for idx, m in enumerate(merged[:2]):  # primary + SPOC2 carry contacts
        p = Person(
            domain=co.domain,
            name=m["name"],
            role=m["role"],
            name_source=m["name_source"],
            is_primary=(idx == 0),
            notes=f"sources: {', '.join(m['sources'])}",
        )
        contact = _person_contact(store, sh, co.domain, m["name"], co.company_name,
                                  refresh, uid=m.get("uid"))
        if contact["phones"]:
            p.phone, p.phone_source = contact["phones"][0], "signalhire"
            stats["phones"] += 1
        if contact.get("emails"):
            p.email, p.email_source = contact["emails"][0], "signalhire"
            stats["emails"] += 1
        if contact.get("linkedin"):
            # Matched-by-company Signalhire LinkedIn. Not namesake-guard confirmed,
            # so flag it (linkedin_confirmed stays False); sales verifies.
            p.linkedin_url = contact["linkedin"]
            p.linkedin_source = "signalhire"
            p.linkedin_confirmed = False
        store.upsert_person(p)
    # any additional founders beyond SPOC2: store without contact lookup
    for m in merged[2:]:
        store.upsert_person(Person(
            domain=co.domain, name=m["name"], role=m["role"],
            name_source=m["name_source"], is_primary=False,
            notes=f"sources: {', '.join(m['sources'])}"))
    stats["founders"] += len(merged)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_enrich(cfg, store, max_enrich=None, refresh=False, clients=None, only_new=False) -> dict:  # noqa: ANN001
    cap = max_enrich if max_enrich is not None else cfg.enrich.max_enrich
    threshold = cfg.judge.fuzzy_threshold
    own_fetcher = False
    if clients is None:
        clients = _build_clients(cfg, store)
        own_fetcher = True

    claude = clients.get("claude")
    registry = clients.get("registry")
    site = clients.get("company_site")
    sh = clients.get("signalhire")
    li = clients.get("linkedin")

    stats = {"enriched": 0, "skipped_existing": 0, "founders": 0, "phones": 0,
             "emails": 0, "signalhire_calls": 0, "claude_calls": 0,
             "quota_reached": False}
    try:
        for co in store.iter_companies(gate_pass=True):
            if stats["enriched"] >= cap:
                log.info("max_enrich_reached", cap=cap)
                break

            # incremental mode: skip firms that already have people rows
            if only_new and store.people_for(co.domain):
                stats["skipped_existing"] += 1
                continue

            try:
                _enrich_one(co, store, clients, threshold, stats, refresh)
                stats["enriched"] += 1
            except QuotaExceeded as e:
                # Provider quota (e.g. SignalHire daily search) exhausted. Stop
                # cleanly — work so far is cached; the next run resumes here.
                log.info("enrich_stopped_quota", provider=e.provider, metric=e.metric,
                         enriched=stats["enriched"])
                stats["quota_reached"] = True
                break

        if sh is not None:
            stats["signalhire_calls"] = sh.search_calls + sh.enrich_calls
            stats["signalhire_credits_left"] = sh.last_credits_left
        if claude is not None:
            stats["claude_calls"] = claude.calls
            stats["claude_tokens"] = claude.tokens
        log.info("enrich_complete", **stats)
        return stats
    finally:
        if own_fetcher:
            f = clients.get("fetcher")
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass
