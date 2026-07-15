"""Shared HubSpot HTTP client: auth, retries, rate limiting, CRM helpers.

Every HubSpot module (setup / sync / workflow) drives this one client.

Rate limiting is proactive AND reactive (scalingPlanV2 §Error handling):
  * proactive — a sliding-window pacer keeps us under HubSpot's private-app
    limit (100 requests / 10 s) at a 10% safety margin;
  * reactive — 429/5xx retried honoring ``Retry-After``; a low
    ``X-HubSpot-RateLimit-Remaining`` header pauses briefly.

HTTP is injectable (``responder(method, path, json) -> (status, dict)``) so
tests run fully offline.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Optional

from ..logging_setup import get_logger

log = get_logger("lh2.hubspot")

BASE_URL = "https://api.hubapi.com"
Responder = Callable[[str, str, Optional[dict]], "tuple[int, dict]"]


class HubspotError(Exception):
    pass


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class HubspotClient:
    def __init__(self, token: Optional[str] = None, responder: Optional[Responder] = None,
                 timeout_s: int = 40, max_retries: int = 4,
                 rate_limit: int = 100, rate_window_s: float = 10.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.token = token
        self._responder = responder
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.rate_limit = rate_limit
        self.rate_window_s = rate_window_s
        self._sleep = sleep
        self._clock = clock
        self._sent: deque = deque()      # timestamps of recent real HTTP requests
        self.calls = 0

    # -- rate limiting ------------------------------------------------------ #
    def _pace(self) -> None:
        """Block until another request fits the sliding window (90% of limit)."""
        limit = max(1, int(self.rate_limit * 0.9))
        now = self._clock()
        while self._sent and now - self._sent[0] > self.rate_window_s:
            self._sent.popleft()
        if len(self._sent) >= limit:
            wait = self.rate_window_s - (now - self._sent[0])
            if wait > 0:
                log.info("hubspot_rate_pace", wait=round(wait, 2))
                self._sleep(wait)
        self._sent.append(self._clock())

    # -- transport ----------------------------------------------------------- #
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
            self._pace()
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    r = client.request(method, url, json=json, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                self._sleep(min(10.0, 2 ** attempt))
                continue
            remaining = r.headers.get("X-HubSpot-RateLimit-Remaining")
            if remaining is not None:
                try:
                    if int(remaining) < 5:       # nearly out — let the window refill
                        self._sleep(1.0)
                except ValueError:
                    pass
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", min(10.0, 2 ** attempt)))
                log.info("hubspot_retry", status=r.status_code, attempt=attempt, wait=wait)
                self._sleep(wait)
                continue
            body = r.json() if r.content else {}
            return r.status_code, body
        raise HubspotError(f"hubspot request failed after retries: {method} {path}: {last_exc}")

    # -- properties ---------------------------------------------------------- #
    def property_exists(self, object_type: str, name: str) -> bool:
        status, _ = self._request("GET", f"/crm/v3/properties/{object_type}/{name}")
        return status == 200

    def create_property(self, object_type: str, spec: dict, group: str) -> None:
        body = {"name": spec["name"], "label": spec["label"], "type": spec["type"],
                "fieldType": spec["fieldType"], "groupName": group}
        if "options" in spec:
            body["options"] = spec["options"]
        if spec.get("hasUniqueValue"):
            body["hasUniqueValue"] = True
        status, resp = self._request("POST", f"/crm/v3/properties/{object_type}", body)
        # HubSpot requires unique property LABELS per object; a standard prop
        # (e.g. hs_linkedin_url "LinkedIn URL") can collide. The NAME is what we
        # write to, so retry with a suffixed label.
        if status == 400 and "NON_UNIQUE_PROPERTY_LABEL" in str(resp):
            body["label"] = f"{spec['label']} (LH2)"
            status, resp = self._request("POST", f"/crm/v3/properties/{object_type}", body)
        if status not in (200, 201):
            raise HubspotError(f"create property {object_type}.{spec['name']} failed: {status} {resp}")

    # -- pipelines ----------------------------------------------------------- #
    def list_deal_pipelines(self) -> list[dict]:
        status, resp = self._request("GET", "/crm/v3/pipelines/deals")
        if status != 200:
            raise HubspotError(f"list pipelines failed: {status} {resp}")
        return resp.get("results", [])

    def get_deal_pipeline(self, label: str) -> Optional[dict]:
        for p in self.list_deal_pipelines():
            if p.get("label") == label:
                return p
        return None

    # -- objects ------------------------------------------------------------- #
    def batch_upsert(self, object_type: str, inputs: list[dict]) -> list[dict]:
        """Upsert by a unique-value idProperty (atomic; immune to search-index lag)."""
        results: list[dict] = []
        for chunk in _chunks(inputs, 100):
            status, resp = self._request(
                "POST", f"/crm/v3/objects/{object_type}/batch/upsert", {"inputs": chunk})
            if status not in (200, 201, 207):
                raise HubspotError(f"batch upsert {object_type} failed: {status} {resp}")
            results.extend(resp.get("results", []))
        return results

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

    def search_ids(self, object_type: str, prop: str, values: list[str]) -> dict:
        """{property_value(lower): hubspot_id} for existing objects with prop IN values."""
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

    def search_all(self, object_type: str, filters: list[dict], properties: list[str]) -> list[dict]:
        """Every object matching ``filters`` (paginated), with ``properties``."""
        out: list[dict] = []
        after = None
        while True:
            body = {"filterGroups": [{"filters": filters}], "properties": properties, "limit": 100}
            if after:
                body["after"] = after
            status, resp = self._request("POST", f"/crm/v3/objects/{object_type}/search", body)
            if status != 200:
                raise HubspotError(f"search {object_type} failed: {status} {resp}")
            out.extend(resp.get("results", []))
            after = resp.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    def associate_default(self, from_type: str, to_type: str, pairs: list[tuple]) -> None:
        """Create default (unlabeled) associations for (from_id, to_id) pairs."""
        for chunk in _chunks(pairs, 100):
            inputs = [{"from": {"id": str(f)}, "to": {"id": str(t)}} for f, t in chunk]
            status, resp = self._request(
                "POST",
                f"/crm/v4/associations/{from_type}/{to_type}/batch/associate/default",
                {"inputs": inputs})
            if status not in (200, 201, 207):
                raise HubspotError(f"associate {from_type}->{to_type} failed: {status} {resp}")
