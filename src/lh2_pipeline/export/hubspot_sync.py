"""HubSpot nightly sync: Companies + Contacts + Deals, and the feedback pull.

Per scalingPlanV2 §2, each qualified lead becomes:
  * a **Company** — upserted by the unique ``lh2_domain`` key (atomic, race-free);
  * a **Contact** (SPOC 1, primary founder) — upserted by email;
  * a **Contact** (SPOC 2, optional; no email) — created once, idempotent via a
    local cache key (``hubspot:spoc2:<domain>`` → contact id);
  * a **Deal** in the "Codebase Acquisition" pipeline at "New Lead" — created
    ONLY if missing (unique ``lh2_domain`` deal key backstops the search), and
    NEVER updated afterwards: deals carry workflow state owned by sales, so a
    re-sync must not drag a worked deal back to "New Lead".

Never fabricates: only non-empty values are sent.
"""

from __future__ import annotations

from typing import Optional

from ..logging_setup import get_logger
from ..models import utcnow
from .hubspot_client import HubspotClient, HubspotError
from .hubspot_setup import PIPELINE_NAME

log = get_logger("lh2.hubspot")


# --------------------------------------------------------------------------- #
# Row → HubSpot property mapping
# --------------------------------------------------------------------------- #
def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _is_qualified(people) -> bool:  # noqa: ANN001
    if not people:
        return False
    p = people[0]
    return bool(p.name and p.name != "(verify)" and p.linkedin_url and p.phone and p.email)


def _company_props(co, source_label: str, synced_at: str) -> dict:  # noqa: ANN001
    props = {
        "name": co.company_name,
        "domain": co.domain,
        "lh2_domain": co.domain,          # unique-value key for idempotent upsert
        "city": co.city,
        "country": co.hq_country,
        "founded_year": co.founded_year,
        "size_bucket": co.size_bucket,
        "segment": co.segment,
        "pipeline_source": source_label,
        "pipeline_synced_at": synced_at,
    }
    return {k: v for k, v in props.items() if v not in (None, "")}


def _contact_props(person, spoc_type: str = "Primary") -> dict:  # noqa: ANN001
    first, last = _split_name(person.name)
    props = {
        "email": person.email,
        "firstname": first,
        "lastname": last,
        "phone": person.phone,
        "linkedin_url": person.linkedin_url,
        "contact_role": person.role,
        "spoc_type": spoc_type,
    }
    return {k: v for k, v in props.items() if v not in (None, "")}


def _deal_props(co, stage_id: str, pipeline_id: str) -> dict:  # noqa: ANN001
    return {
        "dealname": f"{co.company_name} - Codebase Acquisition",
        "pipeline": pipeline_id,
        "dealstage": stage_id,
        "lh2_domain": co.domain,          # unique-value key: one deal per company
        "lead_source": "LH2 Pipeline",
        "email_version_sent": "None",
        "call_attempt_count": 0,
        "script_status": "Not Started",
    }


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
def run_hubspot_sync(cfg, store, client: Optional[HubspotClient] = None,  # noqa: ANN001
                     limit: Optional[int] = None, dry_run: bool = False) -> dict:
    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    synced_at = utcnow().strftime("%Y-%m-%d")
    source_label = getattr(cfg.hubspot, "pipeline_source", "LH2 pipeline")

    rows: list[tuple] = []                 # (company, primary_person, spoc2_or_None)
    for co in store.iter_companies(gate_pass=True):
        people = store.people_for(co.domain)
        if not _is_qualified(people):
            continue
        spoc2 = people[1] if len(people) > 1 else None
        if spoc2 is not None and (not spoc2.name or spoc2.name == "(verify)"):
            spoc2 = None
        rows.append((co, people[0], spoc2))
        if limit and len(rows) >= limit:
            break

    stats = {"companies": len(rows), "contacts": len(rows), "deals": 0,
             "spoc2_contacts": 0, "associations": 0, "dry_run": dry_run}
    if dry_run or not rows:
        stats["deals"] = len(rows)         # candidates (existing ones would be skipped live)
        log.info("hubspot_sync_preview", **stats)
        return stats

    # 0) resolve the deal pipeline + its "New Lead" stage id (labels → internal ids)
    pipeline = hc.get_deal_pipeline(PIPELINE_NAME)
    if pipeline is None:
        raise HubspotError(f"pipeline '{PIPELINE_NAME}' not found — run `lh2 hubspot-setup` first")
    stage_ids = {s["label"]: s["id"] for s in pipeline.get("stages", [])}
    new_lead_id = stage_ids.get("New Lead")
    if not new_lead_id:
        raise HubspotError("stage 'New Lead' not found in the pipeline — run `lh2 hubspot-setup`")

    # 1) Upsert companies (unique lh2_domain) + primary contacts (email) — both
    # atomic unique keys → truly idempotent on back-to-back runs.
    co_results = hc.batch_upsert("companies", [
        {"idProperty": "lh2_domain", "id": co.domain,
         "properties": _company_props(co, source_label, synced_at)} for co, _, _ in rows])
    ct_results = hc.batch_upsert("contacts", [
        {"idProperty": "email", "id": p.email, "properties": _contact_props(p)}
        for _, p, _ in rows])
    domain_to_cid = {str(r.get("properties", {}).get("lh2_domain", "")).lower(): r["id"]
                     for r in co_results if r.get("id")}
    email_to_ctid = {str(r.get("properties", {}).get("email", "")).lower(): r["id"]
                     for r in ct_results if r.get("id")}

    # 2) Associate primary contact -> company.
    pairs = []
    for co, p, _ in rows:
        cid = domain_to_cid.get(co.domain.lower())
        ctid = email_to_ctid.get(p.email.strip().lower())
        if cid and ctid:
            pairs.append((ctid, cid))
    if pairs:
        hc.associate_default("contacts", "companies", pairs)
    stats["associations"] = len(pairs)

    # 3) SPOC 2 contacts (no email → can't upsert). Created once; idempotency via
    # the local cache (deterministic — immune to name-search flakiness).
    spoc2_pairs = []
    for co, _, s2 in rows:
        if s2 is None:
            continue
        cache_key = f"hubspot:spoc2:{co.domain}"
        if store.cache_get(cache_key):
            continue
        props = _contact_props(s2, spoc_type="Secondary")
        props.pop("email", None)
        status, resp = hc._request("POST", "/crm/v3/objects/contacts", {"properties": props})
        if status in (200, 201) and resp.get("id"):
            store.cache_set(cache_key, resp["id"])
            cid = domain_to_cid.get(co.domain.lower())
            if cid:
                spoc2_pairs.append((resp["id"], cid))
            stats["spoc2_contacts"] += 1
        else:
            log.info("hubspot_spoc2_create_failed", domain=co.domain, status=status)
    if spoc2_pairs:
        hc.associate_default("contacts", "companies", spoc2_pairs)

    # 4) Deals — create ONLY if missing (search by unique lh2_domain; the unique
    # constraint also hard-blocks any duplicate the search might miss). Existing
    # deals are left completely untouched (their stage belongs to sales).
    existing = hc.search_ids("deals", "lh2_domain", [co.domain for co, _, _ in rows])
    to_create = [(co, p) for co, p, _ in rows if co.domain.lower() not in existing]
    created_deals: list[tuple] = []       # (deal_id, domain, email)
    if to_create:
        try:
            results = hc.batch_create("deals", [
                {"properties": _deal_props(co, new_lead_id, pipeline["id"])} for co, _ in to_create])
        except HubspotError as e:
            # A uniqueness CONFLICT here means the search index lagged an existing
            # deal — exactly what the unique key is for. Nothing was duplicated.
            log.info("hubspot_deals_create_conflict", err=str(e))
            results = []
        by_domain = {str(r.get("properties", {}).get("lh2_domain", "")).lower(): r["id"]
                     for r in results if r.get("id")}
        for co, p in to_create:
            did = by_domain.get(co.domain.lower())
            if did:
                created_deals.append((did, co.domain, p.email))
    stats["deals"] = len(created_deals)

    # 5) Associate each new deal with its company AND primary contact.
    deal_co = [(did, domain_to_cid[dom.lower()]) for did, dom, _ in created_deals
               if dom.lower() in domain_to_cid]
    deal_ct = [(did, email_to_ctid[em.strip().lower()]) for did, _, em in created_deals
               if em and em.strip().lower() in email_to_ctid]
    if deal_co:
        hc.associate_default("deals", "companies", deal_co)
    if deal_ct:
        hc.associate_default("deals", "contacts", deal_ct)

    stats["hubspot_calls"] = hc.calls
    log.info("hubspot_sync", **stats)
    return stats


# --------------------------------------------------------------------------- #
# Pull — read caller call-feedback back into the pipeline (the feedback loop)
# --------------------------------------------------------------------------- #
_FEEDBACK_PROPS = ["email", "call_outcome", "call_notes", "call_date", "next_step"]


def run_hubspot_pull(cfg, store, client: Optional[HubspotClient] = None,  # noqa: ANN001
                     dry_run: bool = False) -> dict:
    """Read call-feedback (outcome/notes/date/next-step) that callers filled on our
    HubSpot contacts back into the local ``crm_feedback`` table, keyed to the
    company domain — so downstream targeting/scoring can use real call results."""
    from collections import Counter

    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    email_to_domain = store.email_domain_map()

    contacts = hc.search_all(
        "contacts",
        [{"propertyName": "spoc_type", "operator": "EQ", "value": "Primary"}],
        _FEEDBACK_PROPS)

    pulled = 0
    outcomes: Counter = Counter()
    for c in contacts:
        pr = c.get("properties", {}) or {}
        outcome, notes, nxt = pr.get("call_outcome"), pr.get("call_notes"), pr.get("next_step")
        # only rows a caller actually touched (ignore the default "Not Called"/empty)
        if not (notes or nxt or (outcome and outcome != "Not Called")):
            continue
        email = (pr.get("email") or "").strip().lower()
        domain = email_to_domain.get(email)
        if not dry_run:
            store.upsert_feedback(domain, email, outcome, notes, pr.get("call_date"), nxt)
        pulled += 1
        outcomes[outcome or "(notes only)"] += 1

    stats = {"contacts_scanned": len(contacts), "feedback_pulled": pulled,
             "outcomes": dict(outcomes), "dry_run": dry_run}
    log.info("hubspot_pull", **{k: v for k, v in stats.items() if k != "outcomes"})
    return stats
