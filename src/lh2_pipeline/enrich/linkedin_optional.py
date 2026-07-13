"""Optional paid LinkedIn enrichment — Proxycurl / Coresignal adapter.

OFF by default (enrich.linkedin_optional.enabled). This is the only paid
LinkedIn-derived component. It returns *candidate* profiles (name + headline +
experience text + url); the namesake guard (judge.match) decides whether any url
is actually written. Never writes a url directly.

Adapter contract: inject a ``responder(payload) -> dict`` for tests; production
wires the provider endpoint + key.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..logging_setup import get_logger

log = get_logger("lh2.linkedin")

Responder = Callable[[dict], dict]

PROVIDERS = {
    "proxycurl": "https://nubela.co/proxycurl/api",
    "coresignal": "https://api.coresignal.com/cdapi/v1",
}


class LinkedinClient:
    def __init__(
        self,
        provider: str = "proxycurl",
        api_key: Optional[str] = None,
        responder: Optional[Responder] = None,
        timeout_s: int = 30,
    ):
        self.provider = provider
        self.base_url = PROVIDERS.get(provider, PROVIDERS["proxycurl"])
        self.api_key = api_key
        self._responder = responder
        self.timeout_s = timeout_s
        self.calls = 0

    def _raw_request(self, payload: dict) -> dict:
        if self._responder is not None:
            return self._responder(payload)
        if not self.api_key:
            raise RuntimeError(f"{self.provider} API key is not set")
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.get(self.base_url, params=payload, headers=headers)
            r.raise_for_status()
            self.calls += 1
            return r.json()

    def candidates(self, *, domain: str, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Return candidate profiles: {name, headline, experience_text, url}.
        These are passed to the namesake guard before any url is trusted."""
        payload: dict[str, Any] = {"company_domain": domain}
        if name:
            payload["name"] = name
        resp = self._raw_request(payload)
        people = resp.get("people") or resp.get("profiles") or resp.get("results") or []
        out: list[dict[str, Any]] = []
        for p in people if isinstance(people, list) else []:
            if not isinstance(p, dict):
                continue
            out.append(
                {
                    "name": str(p.get("name") or p.get("full_name") or "").strip(),
                    "headline": str(p.get("headline") or p.get("occupation") or "").strip(),
                    "experience_text": str(
                        p.get("experience_text") or p.get("summary") or p.get("experiences") or ""
                    ).strip(),
                    "url": str(p.get("url") or p.get("linkedin_url") or p.get("profile_url") or "").strip(),
                }
            )
        return out
