"""Phase 5c — HubSpot CRM sync.

Two entry points, both driven by a HubSpot **private-app token** (HUBSPOT_API_KEY):

  * ``run_hubspot_setup`` — idempotently create the custom Company/Contact
    properties and the "Codebase Acquisition" deal pipeline via the HubSpot API,
    so nothing has to be clicked in the UI. Existing props/pipeline are skipped.
  * ``run_hubspot_sync`` — push Qualified leads: batch-**upsert** Companies (keyed
    on ``domain``) + primary-founder Contacts (keyed on ``email``), then associate
    each contact to its company. Upsert + natural keys → re-runs never duplicate.

Never fabricates: only non-empty values are sent. HTTP is injectable
(``responder(method, path, json) -> (status, dict)``) so tests run fully offline.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from ..logging_setup import get_logger
from ..models import utcnow

log = get_logger("lh2.hubspot")

BASE_URL = "https://api.hubapi.com"
Responder = Callable[[str, str, Optional[dict]], "tuple[int, dict]"]


# --------------------------------------------------------------------------- #
# Schema to create (idempotent)
# --------------------------------------------------------------------------- #
def _enum(options: list[str]) -> list[dict]:
    return [{"label": o, "value": o, "displayOrder": i} for i, o in enumerate(options)]


COMPANY_PROPERTIES = [
    {"name": "founded_year", "label": "Founded Year", "type": "number", "fieldType": "number"},
    {"name": "size_bucket", "label": "Size Bucket", "type": "enumeration", "fieldType": "select",
     "options": _enum(["1-100", "100-500", "500-1000"])},
    {"name": "headcount_source", "label": "Headcount Source", "type": "string", "fieldType": "text"},
    {"name": "segment", "label": "Segment", "type": "string", "fieldType": "text"},
    {"name": "pipeline_source", "label": "Pipeline Source", "type": "string", "fieldType": "text"},
    {"name": "pipeline_notes", "label": "Pipeline Notes", "type": "string", "fieldType": "textarea"},
    {"name": "pipeline_synced_at", "label": "Pipeline Synced At", "type": "date", "fieldType": "date"},
]
CONTACT_PROPERTIES = [
    {"name": "linkedin_url", "label": "LinkedIn URL", "type": "string", "fieldType": "text"},
    {"name": "contact_role", "label": "Contact Role", "type": "string", "fieldType": "text"},
    {"name": "spoc_type", "label": "SPOC Type", "type": "enumeration", "fieldType": "select",
     "options": _enum(["Primary", "Secondary"])},
]
COMPANY_GROUP = "companyinformation"      # standard HubSpot property group
CONTACT_GROUP = "contactinformation"

PIPELINE_NAME = "Codebase Acquisition"
# stage -> win probability (1.0 = closed-won, 0.0 = closed-lost, per HubSpot convention)
PIPELINE_STAGES = [
    ("New Lead", 0.1), ("Contacted", 0.2), ("Replied", 0.3), ("Discovery Call", 0.4),
    ("Interested", 0.5), ("Offer Sent", 0.7), ("Negotiating", 0.85),
    ("Won", 1.0), ("Lost", 0.0),
]


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class HubspotError(Exception):
    pass


class HubspotClient:
    def __init__(self, token: Optional[str] = None, responder: Optional[Responder] = None,
                 timeout_s: int = 40, max_retries: int = 4):
        self.token = token
        self._responder = responder
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.calls = 0

    def _request(self, method: str, path: str, json: Optional[dict] = None) -> tuple[int, dict]:
        self.calls += 1
        if self._responder is not None:
            return self._responder(method, path, json)
        if not self.token:
            raise RuntimeError("HUBSPOT_API_KEY is not set")
        import httpx

        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        url = BASE_URL + path
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    r = client.request(method, url, json=json, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                time.sleep(min(10.0, 2 ** attempt))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                # rate-limited / server error → honor Retry-After then retry
                wait = float(r.headers.get("Retry-After", min(10.0, 2 ** attempt)))
                log.info("hubspot_retry", status=r.status_code, attempt=attempt, wait=wait)
                time.sleep(wait)
                continue
            body = r.json() if r.content else {}
            return r.status_code, body
        raise HubspotError(f"hubspot request failed after retries: {method} {path}: {last_exc}")

    # -- properties / pipeline (setup) ------------------------------------- #
    def property_exists(self, object_type: str, name: str) -> bool:
        status, _ = self._request("GET", f"/crm/v3/properties/{object_type}/{name}")
        return status == 200

    def create_property(self, object_type: str, spec: dict, group: str) -> None:
        body = {"name": spec["name"], "label": spec["label"], "type": spec["type"],
                "fieldType": spec["fieldType"], "groupName": group}
        if "options" in spec:
            body["options"] = spec["options"]
        status, resp = self._request("POST", f"/crm/v3/properties/{object_type}", body)
        # HubSpot requires unique property LABELS across an object; a standard prop
        # (e.g. hs_linkedin_url labelled "LinkedIn URL") can collide. The property
        # NAME is what our sync writes to, so just retry with a suffixed label.
        if status == 400 and "NON_UNIQUE_PROPERTY_LABEL" in str(resp):
            body["label"] = f"{spec['label']} (LH2)"
            status, resp = self._request("POST", f"/crm/v3/properties/{object_type}", body)
        if status not in (200, 201):
            raise HubspotError(f"create property {object_type}.{spec['name']} failed: {status} {resp}")

    def pipeline_exists(self, label: str) -> bool:
        status, resp = self._request("GET", "/crm/v3/pipelines/deals")
        if status != 200:
            raise HubspotError(f"list pipelines failed: {status} {resp}")
        return any(p.get("label") == label for p in resp.get("results", []))

    def create_deal_pipeline(self, label: str, stages: list[tuple]) -> None:
        body = {
            "label": label,
            "displayOrder": 0,
            "stages": [
                {"label": name, "displayOrder": i, "metadata": {"probability": str(prob)}}
                for i, (name, prob) in enumerate(stages)
            ],
        }
        status, resp = self._request("POST", "/crm/v3/pipelines/deals", body)
        if status not in (200, 201):
            raise HubspotError(f"create pipeline failed: {status} {resp}")

    # -- objects (sync) ---------------------------------------------------- #
    def batch_upsert(self, object_type: str, inputs: list[dict]) -> list[dict]:
        """Upsert up to 100 objects via idProperty; returns the result objects
        (each with HubSpot ``id`` + echoed ``properties``)."""
        results: list[dict] = []
        for chunk in _chunks(inputs, 100):
            status, resp = self._request(
                "POST", f"/crm/v3/objects/{object_type}/batch/upsert", {"inputs": chunk})
            if status not in (200, 201, 207):
                raise HubspotError(f"batch upsert {object_type} failed: {status} {resp}")
            results.extend(resp.get("results", []))
        return results

    def search_ids(self, object_type: str, prop: str, values: list[str]) -> dict:
        """Return {property_value(lower): hubspot_id} for existing objects whose
        ``prop`` is IN ``values``. Used when a property isn't a unique-value key
        (e.g. company ``domain``) so we can't upsert by it directly."""
        found: dict[str, str] = {}
        for chunk in _chunks([v for v in values if v], 100):
            status, resp = self._request("POST", f"/crm/v3/objects/{object_type}/search", {
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "IN", "values": chunk}]}],
                "properties": [prop], "limit": 100})
            if status != 200:
                raise HubspotError(f"search {object_type}.{prop} failed: {status} {resp}")
            for r in resp.get("results", []):
                v = r.get("properties", {}).get(prop)
                if v and r.get("id"):
                    found[str(v).lower()] = r["id"]
        return found

    def batch_create(self, object_type: str, inputs: list[dict]) -> list[dict]:
        results: list[dict] = []
        for chunk in _chunks(inputs, 100):
            status, resp = self._request(
                "POST", f"/crm/v3/objects/{object_type}/batch/create", {"inputs": chunk})
            if status not in (200, 201, 207):
                raise HubspotError(f"batch create {object_type} failed: {status} {resp}")
            results.extend(resp.get("results", []))
        return results

    def batch_update(self, object_type: str, inputs: list[dict]) -> list[dict]:
        results: list[dict] = []
        for chunk in _chunks(inputs, 100):
            status, resp = self._request(
                "POST", f"/crm/v3/objects/{object_type}/batch/update", {"inputs": chunk})
            if status not in (200, 201, 207):
                raise HubspotError(f"batch update {object_type} failed: {status} {resp}")
            results.extend(resp.get("results", []))
        return results

    def associate_default(self, from_type: str, to_type: str, pairs: list[tuple]) -> None:
        """Create default (primary) associations for (from_id, to_id) pairs."""
        for chunk in _chunks(pairs, 100):
            inputs = [{"from": {"id": str(f)}, "to": {"id": str(t)}} for f, t in chunk]
            status, resp = self._request(
                "POST",
                f"/crm/v4/associations/{from_type}/{to_type}/batch/associate/default",
                {"inputs": inputs})
            if status not in (200, 201, 207):
                raise HubspotError(f"associate {from_type}->{to_type} failed: {status} {resp}")


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# --------------------------------------------------------------------------- #
# Setup — create properties + pipeline idempotently
# --------------------------------------------------------------------------- #
def run_hubspot_setup(cfg, store=None, client: Optional[HubspotClient] = None,  # noqa: ANN001
                      dry_run: bool = False) -> dict:
    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    created = {"company_props": [], "contact_props": [], "pipeline": None,
               "skipped": []}

    for obj, props, group in (("companies", COMPANY_PROPERTIES, COMPANY_GROUP),
                              ("contacts", CONTACT_PROPERTIES, CONTACT_GROUP)):
        key = "company_props" if obj == "companies" else "contact_props"
        for spec in props:
            if hc.property_exists(obj, spec["name"]):
                created["skipped"].append(f"{obj}.{spec['name']}")
                continue
            if not dry_run:
                hc.create_property(obj, spec, group)
            created[key].append(spec["name"])

    if hc.pipeline_exists(PIPELINE_NAME):
        created["skipped"].append(f"pipeline:{PIPELINE_NAME}")
    elif not dry_run:
        try:
            hc.create_deal_pipeline(PIPELINE_NAME, PIPELINE_STAGES)
            created["pipeline"] = PIPELINE_NAME
        except HubspotError as e:
            # e.g. free/starter tier caps deal pipelines at 1. Non-fatal: the
            # sync pushes companies+contacts (no deals yet), so properties are
            # what matter. Deals can use the existing default pipeline / upgrade.
            created["pipeline_error"] = str(e)
            log.info("hubspot_pipeline_skipped", err=str(e))
    else:
        created["pipeline"] = PIPELINE_NAME

    log.info("hubspot_setup", created_company=len(created["company_props"]),
             created_contact=len(created["contact_props"]),
             pipeline=created["pipeline"], skipped=len(created["skipped"]))
    return created


# --------------------------------------------------------------------------- #
# Sync — push Qualified leads (companies + primary contacts + associations)
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
        "city": co.city,
        "country": co.hq_country,
        "founded_year": co.founded_year,
        "size_bucket": co.size_bucket,
        "segment": co.segment,
        "pipeline_source": source_label,
        "pipeline_synced_at": synced_at,
    }
    return {k: v for k, v in props.items() if v not in (None, "")}


def _contact_props(person) -> dict:  # noqa: ANN001
    first, last = _split_name(person.name)
    props = {
        "email": person.email,
        "firstname": first,
        "lastname": last,
        "phone": person.phone,
        "linkedin_url": person.linkedin_url,
        "contact_role": person.role,
        "spoc_type": "Primary",
    }
    return {k: v for k, v in props.items() if v not in (None, "")}


def run_hubspot_sync(cfg, store, client: Optional[HubspotClient] = None,  # noqa: ANN001
                     limit: Optional[int] = None, dry_run: bool = False) -> dict:
    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    synced_at = utcnow().strftime("%Y-%m-%d")
    source_label = getattr(cfg.hubspot, "pipeline_source", "LH2 pipeline")

    companies: list[tuple] = []      # (domain, properties)
    contact_inputs: list[dict] = []
    # remember which contact email belongs to which company domain (for association)
    email_to_domain: dict[str, str] = {}

    for co in store.iter_companies(gate_pass=True):
        people = store.people_for(co.domain)
        if not _is_qualified(people):
            continue
        primary = people[0]
        companies.append((co.domain, _company_props(co, source_label, synced_at)))
        contact_inputs.append({"idProperty": "email", "id": primary.email,
                               "properties": _contact_props(primary)})
        email_to_domain[primary.email.strip().lower()] = co.domain
        if limit and len(companies) >= limit:
            break

    stats = {"companies": len(companies), "contacts": len(contact_inputs),
             "associations": 0, "dry_run": dry_run}
    if dry_run or not companies:
        log.info("hubspot_sync_preview", **stats)
        return stats

    # 1) COMPANIES — domain isn't a HubSpot unique-value property, so we can't
    # upsert by it. Search existing by domain, then create-or-update. Idempotent.
    existing = hc.search_ids("companies", "domain", [d for d, _ in companies])
    to_update, to_create = [], []
    domain_to_cid: dict[str, str] = {}
    for domain, props in companies:
        cid = existing.get(domain.lower())
        if cid:
            domain_to_cid[domain.lower()] = cid
            to_update.append({"id": cid, "properties": props})
        else:
            to_create.append({"properties": props})
    hc.batch_update("companies", to_update)
    for r in hc.batch_create("companies", to_create):
        d = str(r.get("properties", {}).get("domain", "")).lower()
        if d and r.get("id"):
            domain_to_cid[d] = r["id"]

    # 2) CONTACTS — email IS a unique-value property, so upsert-by-email works.
    ct_results = hc.batch_upsert("contacts", contact_inputs)
    email_to_ctid = {str(r.get("properties", {}).get("email", "")).lower(): r["id"]
                     for r in ct_results if r.get("id")}

    # 2) associate each contact to its company (default/primary association)
    pairs: list[tuple] = []
    for email, domain in email_to_domain.items():
        cid = domain_to_cid.get(domain.lower())
        ctid = email_to_ctid.get(email)
        if cid and ctid:
            pairs.append((ctid, cid))
    if pairs:
        hc.associate_default("contacts", "companies", pairs)
    stats["associations"] = len(pairs)
    stats["hubspot_calls"] = hc.calls

    log.info("hubspot_sync", **stats)
    return stats
